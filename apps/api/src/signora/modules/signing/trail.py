"""Signing events on the envelope's own audit chain, with the request's IP and user agent."""

from __future__ import annotations

from signora.kernel.db import UnitOfWork
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.envelopes import SignerRecipient


def audit(uow: UnitOfWork, recipient: SignerRecipient, action: str) -> None:
    record(
        uow,
        chain=AuditChain.envelope(recipient.workspace_id, recipient.envelope_id),
        actor=AuditActor("recipient", recipient.id, recipient.email),
        action=action,
        subject=Subject("envelope", recipient.envelope_id),
    )
