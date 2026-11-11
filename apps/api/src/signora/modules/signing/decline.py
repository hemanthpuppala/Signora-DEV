"""Decline (Phase 8 LLD §8): final, with a reason; it closes the envelope for everyone."""

from __future__ import annotations

from sqlalchemy import text

from signora.kernel.config import get_settings
from signora.kernel.db import UnitOfWork
from signora.modules.envelopes import lock_envelope, recipient_for_signing, record_declined
from signora.modules.notifications import send_email
from signora.modules.signing import emails
from signora.modules.signing.errors import AlreadySigned, LinkClosed, NotTheirTurn
from signora.modules.signing.service import Signer
from signora.modules.signing.trail import audit


def decline(uow: UnitOfWork, who: Signer, reason: str) -> None:
    """Under the envelope's lock (§6.2); a repeat changes nothing. Consent is not needed: declining
    is how consent is withdrawn (§3)."""
    lock_envelope(uow.session, who.recipient.envelope_id)
    recipient = recipient_for_signing(uow.session, who.recipient.id)
    if recipient is None:
        raise LinkClosed
    if recipient.status == "declined":
        return  # a repeat
    if not recipient.envelope_open:
        raise LinkClosed
    if recipient.status == "signed":
        raise AlreadySigned
    if recipient.kind == "countersigner" and recipient.envelope_status != "signed":
        raise NotTheirTurn
    told = record_declined(uow.session, recipient, reason)
    if told is None:
        return
    uow.session.execute(
        text("DELETE FROM signing_drafts WHERE recipient_id = :r"), {"r": recipient.id}
    )
    audit(uow, recipient, "signing.declined", reason=reason)

    base = str(get_settings().app.public_base_url).rstrip("/")
    url = f"{base}/departments/{told.contacts.department_id}/envelopes/{recipient.envelope_id}"
    subject, body = emails.declined_to_sender(
        name=recipient.name, document=recipient.title, reason=reason, url=url
    )
    for to in dict.fromkeys([told.contacts.sender.email, *told.contacts.notify]):
        send_email(
            uow,
            to=to,
            subject=subject,
            text=body.text,
            html=body.html,
            category="sign_declined",
            workspace_id=recipient.workspace_id,
            dedupe_key=f"sign_declined:{recipient.envelope_id}:{to}",
        )
    subject, body = emails.declined_to_others(document=recipient.title)
    for person in told.others:
        send_email(
            uow,
            to=person.email,
            subject=subject,
            text=body.text,
            html=body.html,
            category="sign_declined",
            workspace_id=recipient.workspace_id,
            dedupe_key=f"sign_declined:{recipient.envelope_id}:{person.email}",
            reply_to=told.contacts.sender.email,
        )
