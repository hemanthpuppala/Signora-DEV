"""Completion (Phase 8 LLD §12): one background job makes the completed document and its
certificate, stores both with their fingerprints, completes the envelope and emails everyone the
two PDFs. A retry never makes a second copy or sends a second email.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from signora.kernel.blobstore import BlobRef, BlobStore, blob_store_from_settings
from signora.kernel.config import get_settings
from signora.kernel.db import UnitOfWork
from signora.kernel.jobs import JobContext, JobKind, JobRegistry, enqueue
from signora.kernel.logging import get_logger
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.documents import version_for_signing
from signora.modules.envelopes import envelope_contacts, lock_envelope, recipient_for_signing
from signora.modules.notifications import AttachedFile, send_email
from signora.modules.rendering import certificate_pdf, render
from signora.modules.signing import certify, drawing, emails

log = get_logger(__name__)
COMPLETE = "envelope.complete"
MAX_ATTEMPTS = 5
MAX_EMAILED = 20 * 1024 * 1024  # bytes: larger than many mailboxes take
MAX_FILE = 200 * 1024 * 1024


def queue(uow: UnitOfWork, envelope_id: uuid.UUID) -> None:
    """Queued in the transaction of the last submit (§12.1), once per envelope."""
    enqueue(
        uow.session,
        COMPLETE,
        {"envelope_id": str(envelope_id)},
        dedupe_key=f"{COMPLETE}:{envelope_id}",
    )


def _put(store: BlobStore, workspace_id: uuid.UUID, data: bytes) -> BlobRef:
    return store.put(workspace_id, io.BytesIO(data), max_bytes=MAX_FILE)


def complete(context: JobContext, *, store: BlobStore) -> None:
    envelope_id = uuid.UUID(context.payload["envelope_id"])
    with context.unit_of_work() as uow:
        anyone = uow.session.execute(
            text(
                "SELECT r.id FROM envelopes e JOIN envelope_recipients r ON r.envelope_id = e.id "
                "WHERE e.id = :e AND e.status = 'signed' "
                "AND r.kind IN ('signer', 'countersigner') ORDER BY r.stage, r.position LIMIT 1"
            ),
            {"e": envelope_id},
        ).scalar_one_or_none()
        recipient = recipient_for_signing(uow.session, anyone) if anyone else None
        if recipient is not None:
            pdf, items = drawing.collect(uow, store, recipient, viewer=None)
            original = version_for_signing(uow.session, recipient.version_id).pdf.sha256
    if recipient is None:  # completed already, or closed meanwhile: nothing to do
        with context.complete():
            return

    # The slow part outside any transaction (§12.1); content-addressed, so a retry stores the same.
    signed = render(pdf, items, envelope_id=envelope_id)
    signed_sha = hashlib.sha256(signed).hexdigest()
    completed_at = datetime.now(UTC)
    with context.unit_of_work() as uow:
        data = certify.facts(
            uow,
            envelope_id,
            original_sha256=original,
            completed_sha256=signed_sha,
            completed_at=completed_at,
        )
    proof = certificate_pdf(data)
    signed_ref = _put(store, recipient.workspace_id, signed)
    proof_ref = _put(store, recipient.workspace_id, proof)

    with context.complete() as uow:
        lock_envelope(uow.session, envelope_id)
        done = uow.session.execute(
            text(
                """
                UPDATE envelopes SET status = 'completed', completed_at = :at,
                    signed_blob = :sb, signed_sha256 = :sh, certificate_blob = :cb,
                    certificate_sha256 = :ch
                WHERE id = :e AND status = 'signed' RETURNING id
                """
            ),
            {
                "e": envelope_id,
                "at": completed_at,
                "sb": signed_ref.token,
                "sh": bytes.fromhex(signed_ref.sha256),
                "cb": proof_ref.token,
                "ch": bytes.fromhex(proof_ref.sha256),
            },
        ).one_or_none()
        if done is None:
            return  # another run completed it
        record(
            uow,
            chain=AuditChain.envelope(recipient.workspace_id, envelope_id),
            actor=AuditActor.system(),
            action="envelope.completed",
            subject=Subject("envelope", envelope_id),
            data={"signed_sha256": signed_ref.sha256, "certificate_sha256": proof_ref.sha256},
        )
        _email_everyone(
            uow, recipient.workspace_id, envelope_id, recipient.title, signed_ref, proof_ref
        )
    log.info("envelope.completed", envelope_id=str(envelope_id))


def _email_everyone(
    uow: UnitOfWork,
    workspace_id: uuid.UUID,
    envelope_id: uuid.UUID,
    title: str,
    signed: BlobRef,
    proof: BlobRef,
) -> None:
    """Everyone gets the two PDFs (§12.2): signers, countersigners, copies, the sender and the Also
    notify list, one email each; without them when the two exceed what mailboxes take."""
    contacts = envelope_contacts(uow.session, envelope_id)
    rows = uow.session.execute(
        text(
            "SELECT kind, name, email FROM envelope_recipients WHERE envelope_id = :e "
            "ORDER BY stage, position"
        ),
        {"e": envelope_id},
    ).all()
    signers = ", ".join(r.name for r in rows if r.kind in ("signer", "countersigner"))
    attach = signed.size + proof.size <= MAX_EMAILED
    files = (
        [
            AttachedFile(signed, f"{title}.pdf"),
            AttachedFile(proof, f"{title} - certificate of completion.pdf"),
        ]
        if attach
        else []
    )
    subject, body = emails.completed(
        document=title, signers=signers, attached=attach, sender_email=contacts.sender.email
    )
    everyone = [r.email for r in rows] + [contacts.sender.email, *contacts.notify]
    for to in dict.fromkeys(everyone):
        send_email(
            uow,
            to=to,
            subject=subject,
            text=body.text,
            html=body.html,
            category="sign_completed",
            workspace_id=workspace_id,
            dedupe_key=f"sign_completed:{envelope_id}:{to}",
            reply_to=contacts.sender.email,
            attachments=files,
        )


def _complete(context: JobContext) -> None:
    complete(context, store=blob_store_from_settings(get_settings().blob_store))


def register(jobs_registry: JobRegistry) -> None:
    jobs_registry.register(
        JobKind(COMPLETE, _complete, max_attempts=MAX_ATTEMPTS, lease=timedelta(minutes=5))
    )
