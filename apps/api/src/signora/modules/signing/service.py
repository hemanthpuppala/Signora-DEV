"""Opening a signing link and acting for its person (Phase 8 LLD §1): transactions and audit."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from sqlalchemy import text

from signora.kernel.config import get_settings
from signora.kernel.db import UnitOfWork
from signora.modules.documents import VersionForSigning, version_for_signing
from signora.modules.envelopes import (
    SignerRecipient,
    envelope_values,
    recipient_for_signing,
    record_opened,
    record_viewed,
)
from signora.modules.envelopes.links import link_key, read_token
from signora.modules.identity_access import current_actor, hash_token
from signora.modules.review import read_set
from signora.modules.signing import codes, consent, sessions, signatures
from signora.modules.signing.document import SignerDocument, build_view
from signora.modules.signing.domain import mask_email, next_step
from signora.modules.signing.errors import (
    AlreadySigned,
    CodeNotRequired,
    ConsentFirst,
    DisclosureChanged,
    LinkClosed,
    NotTheirTurn,
    SessionEnded,
    VerifyFirst,
)
from signora.modules.signing.sessions import COOKIE
from signora.modules.signing.trail import audit
from signora.modules.signing.views import (
    Disclosure,
    DisclosureParagraph,
    DoneView,
    Opened,
    SignerState,
    VerifiedBy,
)


def _idle() -> timedelta:
    return timedelta(minutes=get_settings().signing.session_minutes)


def _key() -> bytes:
    return link_key(get_settings().app.secret_key.get_secret_value())


def _step(uow: UnitOfWork, recipient: SignerRecipient, verified: bool) -> Opened:
    return Opened(
        recipient_id=recipient.id,
        next=next_step(
            signed=recipient.status == "signed",
            needs_code=recipient.require_email_code,
            verified=verified,
            consented=consent.has_consented(uow, recipient.id),
        ),
    )


@dataclass(frozen=True)
class OpenResult:
    opened: Opened
    cookie: str | None  # a new session's cookie value, when one was made


def open_link(uow: UnitOfWork, token: str, cookie: str | None) -> OpenResult:
    """Exchange a link's token for a grant in this browser's session (§1.2). Every way a link
    cannot be used gives the same ``LinkClosed``."""
    claim = read_token(_key(), token)
    recipient = recipient_for_signing(uow.session, claim.recipient_id) if claim else None
    if (
        claim is None
        or recipient is None
        or recipient.link_version != claim.link_version
        or not recipient.envelope_open
        or recipient.kind != "signer"  # countersigners sign in Signora (§7)
    ):
        raise LinkClosed

    session = uow.session
    digest = hash_cookie(cookie)
    issued = None
    if digest is None or not sessions.live_session(session, digest, idle=_idle()):
        issued = sessions.create_session(session)
        digest = issued.digest
    sessions.grant(session, digest, recipient)
    if record_opened(session, recipient):
        audit(uow, recipient, "signing.opened")
    grant = sessions.read_grant(session, digest, recipient.id)
    verified = grant is not None and grant.verified_at is not None
    return OpenResult(_step(uow, recipient, verified), issued.value if issued else None)


def hash_cookie(cookie: str | None) -> bytes | None:
    return hash_token(cookie) if cookie else None


@dataclass(frozen=True)
class Signer:
    """The person a signer request acts for, with their grant in this browser (§1.1.10)."""

    recipient: SignerRecipient
    verified: bool
    digest: bytes  # the browser session's

    @property
    def caller(self) -> str:
        """Who is asking, once checked: this browser session for a signer, the signed-in user for
        a countersigner. Limits are counted against them, never against what a request names."""
        if self.recipient.kind == "countersigner":
            return f"user:{self.recipient.user_id}"
        return f"session:{self.digest.hex()}"


def identify(uow: UnitOfWork, request: Request, recipient_id: uuid.UUID) -> Signer:
    """Who is asking for this person, whatever their envelope's state. A signer: this browser holds
    a live session with the person's grant for their current link (§1.1.10). A countersigner:
    signed in to Signora as the designated user, with the console's CSRF check (§7.1.2, §7.1.7);
    their sign-in is the proof of who they are, so no email code. A stored answer to a submit or a
    decline is replayed after this check alone: the request it answers may have closed the
    envelope since."""
    recipient = recipient_for_signing(uow.session, recipient_id)
    if recipient is not None and recipient.kind == "countersigner":
        actor = current_actor(request)  # 401 when signed out; 403 without the CSRF token
        if actor.user_id != recipient.user_id:
            raise LinkClosed
        return Signer(recipient, verified=True, digest=b"")
    digest = hash_cookie(request.cookies.get(COOKIE))
    if digest is None or not sessions.live_session(uow.session, digest, idle=_idle()):
        raise SessionEnded
    grant = sessions.read_grant(uow.session, digest, recipient_id)
    if grant is None:
        raise SessionEnded
    if recipient is None or recipient.link_version != grant.link_version:
        raise LinkClosed
    return Signer(recipient, grant.verified_at is not None, digest)


def may_act(who: Signer) -> Signer:
    """The person's envelope is open to them now (§1.1.10): a signer's until it closes; a
    countersigner's from their turn, and once they have signed, after completion too."""
    recipient = who.recipient
    if recipient.kind != "countersigner":
        if not recipient.envelope_open:
            raise LinkClosed
        return who
    # A completed envelope stays open to the colleague who countersigned it, to read and download
    # (§9.1); nothing in it can change, as they have signed.
    completed = recipient.envelope_status == "completed" and recipient.status == "signed"
    if not recipient.envelope_open and not completed:
        raise LinkClosed
    if recipient.envelope_status != "signed" and recipient.status != "signed":
        raise NotTheirTurn
    return who


def acting(uow: UnitOfWork, request: Request, recipient_id: uuid.UUID) -> Signer:
    """Who a signing request acts for, checked on every request: who is asking, and that the
    envelope is open to them now."""
    return may_act(identify(uow, request, recipient_id))


def state(uow: UnitOfWork, who: Signer) -> SignerState:
    recipient = who.recipient
    return SignerState(
        recipient_id=recipient.id,
        kind="countersigner" if recipient.kind == "countersigner" else "signer",
        name=recipient.name,
        email_masked=mask_email(recipient.email),
        title=recipient.title,
        document_name=recipient.document_name,
        company=recipient.company,
        sender_name=recipient.sender_name,
        sender_email=recipient.sender_email,
        next=_step(uow, recipient, who.verified).next,
        signed_at=recipient.signed_at,
        disclosure=Disclosure(
            version=consent.VERSION,
            agreement=consent.AGREEMENT,
            paragraphs=[
                DisclosureParagraph(title=p.title, text=p.text)
                for p in consent.disclosure(recipient.company, recipient.sender_email)
            ],
        ),
    )


def send_code(uow: UnitOfWork, who: Signer, *, again: bool) -> codes.CodeSent:
    return codes.send_code(uow, who.recipient, again=again)


def verify(uow: UnitOfWork, who: Signer, code: str) -> Opened:
    """The email code (§2): a match verifies this browser's grant; a wrong try is counted and kept
    even though the request is refused."""
    recipient = who.recipient
    if not recipient.require_email_code:
        raise CodeNotRequired
    tried = codes.try_code(uow, recipient, code)
    if not tried.verified:
        audit(
            uow, recipient, "signing.code_locked" if tried.tries_left == 0 else "signing.code_wrong"
        )
        uow.commit()
        raise codes.wrong_code(tried.tries_left)
    uow.session.execute(
        text(
            "UPDATE signing_grants SET verified_at = now() "
            "WHERE session_hash = :h AND recipient_id = :r"
        ),
        {"h": who.digest, "r": recipient.id},
    )
    audit(uow, recipient, "signing.verified")
    return _step(uow, recipient, verified=True)


def give_consent(uow: UnitOfWork, who: Signer, version: str) -> Opened:
    """Consent to electronic records, once per person (§3). Repeat-safe."""
    recipient = who.recipient
    if recipient.require_email_code and not who.verified:
        raise VerifyFirst
    if version != consent.VERSION:
        raise DisclosureChanged
    if consent.record_consent(uow, recipient):
        audit(uow, recipient, "signing.consented")
    return _step(uow, recipient, who.verified)


def require_ready(uow: UnitOfWork, who: Signer, *, to_change: bool = False) -> None:
    """The document is shown only after the code (when asked) and consent (§2, §3); it is changed
    only until the person has signed."""
    recipient = who.recipient
    if recipient.require_email_code and not who.verified:
        raise VerifyFirst
    if not consent.has_consented(uow, recipient.id):
        raise ConsentFirst
    if to_change and recipient.status == "signed":
        raise AlreadySigned


def version_of(uow: UnitOfWork, who: Signer) -> VersionForSigning:
    require_ready(uow, who)
    return version_for_signing(uow.session, who.recipient.version_id)


def document(uow: UnitOfWork, who: Signer) -> SignerDocument:
    """Every field with what this person may see of it (§4.2). O(F + P + V)."""
    version = version_of(uow, who)
    parties, fields = read_set(uow.session, who.recipient.version_id)
    view = build_view(
        viewer=who.recipient,
        pages=version.pages,
        parties=parties,
        fields=fields,
        values=envelope_values(uow.session, who.recipient.envelope_id),
        drafts=read_drafts(uow, who.recipient.id),
    )
    seen = {
        field.value.partition(":")[2]
        for field in view.fields
        if field.value and field.holds in ("signature", "initials")
    }
    if seen:
        signed = signatures.signed_in_envelope(uow, who.recipient.envelope_id)
        view.signatures = [signed[one] for one in sorted(seen) if one in signed]
    return view


def mark_viewed(uow: UnitOfWork, who: Signer) -> None:
    """The document was shown (§4.5): recorded once, for the sender's timeline."""
    require_ready(uow, who)
    if record_viewed(uow.session, who.recipient):
        audit(uow, who.recipient, "signing.viewed")


def read_drafts(uow: UnitOfWork, recipient_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """A person's saved, unsubmitted values (§4.7)."""
    rows = uow.session.execute(
        text("SELECT field_id, value FROM signing_drafts WHERE recipient_id = :r"),
        {"r": recipient_id},
    )
    return {row.field_id: row.value for row in rows}


def done(uow: UnitOfWork, who: Signer) -> DoneView:
    """What the done screen says (§9.1). Only for someone who has signed, and in this browser only
    after the email code, as the document is (§1.1.7): it names who is still to sign."""
    require_ready(uow, who)
    recipient = who.recipient
    if recipient.status != "signed" or recipient.signed_at is None:
        raise NotTheirTurn
    rows = uow.session.execute(
        text(
            "SELECT kind, name, status FROM envelope_recipients WHERE envelope_id = :e "
            "AND kind IN ('signer', 'countersigner') ORDER BY stage, position"
        ),
        {"e": recipient.envelope_id},
    ).all()
    countersigning = any(r.kind == "countersigner" and r.status != "signed" for r in rows)
    approved = not uow.session.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM version_fields WHERE version_id = :v AND role_id = :p "
            "AND holds IN ('signature', 'initials'))"
        ),
        {"v": recipient.version_id, "p": recipient.party_id},
    ).scalar_one()
    verified: VerifiedBy = (
        "signora_sign_in"
        if recipient.kind == "countersigner"
        else "email_code"
        if recipient.require_email_code
        else "email_link"
    )
    return DoneView(
        signed_at=recipient.signed_at,
        verified_by=verified,
        waiting_for=[r.name for r in rows if r.kind == "signer" and r.status != "signed"],
        countersigning=recipient.company if countersigning else None,
        completed=recipient.envelope_status == "completed",
        approved=approved,
    )
