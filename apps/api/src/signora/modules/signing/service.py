"""Opening a signing link and acting for its person (Phase 8 LLD §1): transactions and audit."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text

from signora.kernel.config import get_settings
from signora.kernel.db import UnitOfWork
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.envelopes import SignerRecipient, recipient_for_signing, record_opened
from signora.modules.envelopes.links import link_key, read_token
from signora.modules.identity_access import hash_token
from signora.modules.signing import sessions
from signora.modules.signing.domain import mask_email, next_step
from signora.modules.signing.errors import LinkClosed, SessionEnded
from signora.modules.signing.views import Opened, SignerState


def _idle() -> timedelta:
    return timedelta(minutes=get_settings().signing.session_minutes)


def _key() -> bytes:
    return link_key(get_settings().app.secret_key.get_secret_value())


def audit(uow: UnitOfWork, recipient: SignerRecipient, action: str) -> None:
    """A signing event on the envelope's own chain, with the request's IP and user agent."""
    record(
        uow,
        chain=AuditChain.envelope(recipient.workspace_id, recipient.envelope_id),
        actor=AuditActor("recipient", recipient.id, recipient.email),
        action=action,
        subject=Subject("envelope", recipient.envelope_id),
    )


def _consented(uow: UnitOfWork, recipient_id: uuid.UUID) -> bool:
    return bool(
        uow.session.execute(
            text("SELECT EXISTS (SELECT 1 FROM signing_consents WHERE recipient_id = :r)"),
            {"r": recipient_id},
        ).scalar_one()
    )


def _step(uow: UnitOfWork, recipient: SignerRecipient, verified: bool) -> Opened:
    return Opened(
        recipient_id=recipient.id,
        next=next_step(
            signed=recipient.status == "signed",
            needs_code=recipient.require_email_code,
            verified=verified,
            consented=_consented(uow, recipient.id),
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


def signer(uow: UnitOfWork, cookie: str | None, recipient_id: uuid.UUID) -> Signer:
    """Check again, on every signer request, that this browser holds the person's grant for their
    current link and that their envelope is still open (§1.1.10)."""
    digest = hash_cookie(cookie)
    if digest is None or not sessions.live_session(uow.session, digest, idle=_idle()):
        raise SessionEnded
    grant = sessions.read_grant(uow.session, digest, recipient_id)
    if grant is None:
        raise SessionEnded
    recipient = recipient_for_signing(uow.session, recipient_id)
    if (
        recipient is None
        or recipient.link_version != grant.link_version
        or not recipient.envelope_open
    ):
        raise LinkClosed
    return Signer(recipient, grant.verified_at is not None)


def state(uow: UnitOfWork, who: Signer) -> SignerState:
    recipient = who.recipient
    return SignerState(
        recipient_id=recipient.id,
        name=recipient.name,
        email_masked=mask_email(recipient.email),
        title=recipient.title,
        company=recipient.company,
        sender_name=recipient.sender_name,
        sender_email=recipient.sender_email,
        next=_step(uow, recipient, who.verified).next,
        signed_at=recipient.signed_at,
    )
