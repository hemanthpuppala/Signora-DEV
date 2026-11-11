"""The countersigners' turn (Phase 8 LLD §7.1.1): when the last signer signs, each countersigner is
emailed a link to their countersign page, and the sender and the Also notify list are told."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from signora.kernel.config import get_settings
from signora.kernel.db import UnitOfWork
from signora.modules.envelopes import SignerRecipient, envelope_contacts, people
from signora.modules.notifications import send_email
from signora.modules.signing import emails


def _signer_names(uow: UnitOfWork, envelope_id: uuid.UUID) -> str:
    names = uow.session.execute(
        text(
            "SELECT name FROM envelope_recipients WHERE envelope_id = :e AND kind = 'signer' "
            "ORDER BY position"
        ),
        {"e": envelope_id},
    ).scalars()
    listed = [str(name) for name in names]
    return listed[0] if len(listed) == 1 else ", ".join(listed[:-1]) + " and " + listed[-1]


def countersigners_turn(
    uow: UnitOfWork, last: SignerRecipient, countersigners: list[uuid.UUID]
) -> None:
    base = str(get_settings().app.public_base_url).rstrip("/")
    contacts = envelope_contacts(uow.session, last.envelope_id)
    signers = _signer_names(uow, last.envelope_id)
    for recipient_id, person in people(uow.session, countersigners):
        subject, body = emails.countersign_turn(
            company=last.company,
            document=last.title,
            signers=signers,
            url=f"{base}/countersign/{recipient_id}",
        )
        send_email(
            uow,
            to=person.email,
            subject=subject,
            text=body.text,
            html=body.html,
            category="countersign_request",
            workspace_id=last.workspace_id,
            dedupe_key=f"countersign_request:{recipient_id}",
            reply_to=contacts.sender.email,
        )
    page = f"{base}/departments/{contacts.department_id}/envelopes/{last.envelope_id}"
    subject, body = emails.signers_signed(document=last.title, signers=signers, url=page)
    for to in dict.fromkeys([contacts.sender.email, *contacts.notify]):
        send_email(
            uow,
            to=to,
            subject=subject,
            text=body.text,
            html=body.html,
            category="signers_signed",
            workspace_id=last.workspace_id,
            dedupe_key=f"signers_signed:{last.envelope_id}:{to}",
        )
