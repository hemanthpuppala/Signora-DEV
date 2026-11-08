"""Processing one version in the background (Phase 4 LLD topic 3).

Each version is its own ``document.process`` job, so versions are processed in parallel up to the
worker's concurrency. The job is repeat-safe: a version past Processing is left alone, and the
final write only applies while the version is still Processing.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import timedelta
from io import BytesIO
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.blobstore import BlobRef, BlobStore
from signora.kernel.db import UnitOfWork
from signora.kernel.events import DomainEvent, bus
from signora.kernel.jobs import JobContext, enqueue
from signora.kernel.logging import get_logger
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.documents.conversion import ConversionRefusedError, docx_to_pdf
from signora.modules.documents.current import promote_if_newest
from signora.modules.documents.pdf import (
    DamagedPdfError,
    PasswordRequiredError,
    Prepared,
    TooManyPagesError,
    prepare,
)

log = get_logger("signora.documents")

PROCESS = "document.process"
MAX_ATTEMPTS = 8  # the job backoff: 30 s doubling to 1 h (backbone LLD §1.4)
LEASE = timedelta(minutes=3)  # renewed while running; a conversion may wait 120 s in Gotenberg


class DocumentVersionProcessed(DomainEvent):
    """A version is ready for field detection (Phase 5 subscribes)."""

    document_id: uuid.UUID
    version_id: uuid.UUID


@dataclass(frozen=True)
class _Work:
    id: uuid.UUID
    workspace_id: uuid.UUID
    document_id: uuid.UUID
    version_no: int
    status: str
    source_kind: str
    source_sha256: str
    source_bytes: int
    unlocked_sha256: str | None


def enqueue_processing(session: Session, version_id: uuid.UUID) -> None:
    """Queue the job in the caller's transaction (it runs only if the caller commits)."""
    enqueue(session, PROCESS, {"version_id": str(version_id)})


def _load(uow: UnitOfWork, version_id: uuid.UUID) -> _Work | None:
    found = uow.session.execute(
        text(
            "SELECT id, workspace_id, document_id, version_no, status, source_kind, source_sha256, "
            "source_bytes, unlocked_sha256 FROM document_versions WHERE id = :id"
        ),
        {"id": version_id},
    ).one_or_none()
    return _Work(**found._mapping) if found is not None else None


def _read(store: BlobStore, workspace_id: uuid.UUID, sha256: str) -> bytes:
    # Size is not known for an unlocked copy here; the key is the hash alone.
    with store.open(BlobRef(workspace_id=workspace_id, sha256=sha256, size=0)) as handle:
        return handle.read()


def _audit(uow: UnitOfWork, work: _Work, action: str, **data: Any) -> None:
    record(
        uow,
        chain=AuditChain.workspace(work.workspace_id),
        actor=AuditActor.system(),
        action=action,
        subject=Subject("document", work.document_id),
        data={"version_id": str(work.id), **data},
    )


def _fail(
    context: JobContext,
    work: _Work,
    code: str,
    *,
    temporary: bool,
    page_count: int | None = None,
) -> None:
    with context.complete() as uow:
        changed = uow.session.execute(
            text(
                "UPDATE document_versions SET status = 'failed', failure_code = :code, "
                "failure_temporary = :temporary, page_count = coalesce(:pages, page_count) "
                "WHERE id = :id AND status = 'processing' RETURNING id"
            ),
            {"id": work.id, "code": code, "temporary": temporary, "pages": page_count},
        ).one_or_none()
        if changed is not None:
            _audit(uow, work, "document.version_failed", reason=code, temporary=temporary)


def _needs_password(context: JobContext, work: _Work) -> None:
    with context.complete() as uow:
        uow.session.execute(
            text(
                "UPDATE document_versions SET status = 'needs_password' "
                "WHERE id = :id AND status = 'processing'"
            ),
            {"id": work.id},
        )


def _done(context: JobContext, work: _Work, prepared: Prepared, store: BlobStore) -> None:
    ref = store.put(work.workspace_id, BytesIO(prepared.pdf), max_bytes=len(prepared.pdf))
    status = "needs_ocr" if prepared.pages_without_text else "processed"
    with context.complete() as uow:
        changed = uow.session.execute(
            text(
                "UPDATE document_versions SET status = :status, pdf_sha256 = :h, pdf_bytes = :b, "
                "page_count = :n, pages = CAST(:pages AS jsonb), pages_without_text = :without, "
                "processed_at = now() WHERE id = :id AND status = 'processing' RETURNING id"
            ),
            {
                "id": work.id,
                "status": status,
                "h": ref.sha256,
                "b": ref.size,
                "n": len(prepared.pages),
                "pages": json.dumps([asdict(page) for page in prepared.pages]),
                "without": prepared.pages_without_text,
            },
        ).one_or_none()
        if changed is None:
            return
        if status == "processed":
            # Ready in this phase means processed; Phase 5 moves this to "AI processing done".
            promotion = promote_if_newest(uow.session, work.document_id, work.id, work.version_no)
            if promotion.promoted:
                _audit(
                    uow,
                    work,
                    "document.current_version_changed",
                    old=promotion.previous,
                    new=work.version_no,
                    automatic=True,
                )
            bus.publish(
                uow.session,
                DocumentVersionProcessed(
                    workspace_id=work.workspace_id, document_id=work.document_id, version_id=work.id
                ),
            )


def process_version(
    context: JobContext, *, store: BlobStore, gotenberg_url: str, max_pages: int
) -> None:
    version_id = uuid.UUID(context.payload["version_id"])
    with context.unit_of_work() as uow:
        work = _load(uow, version_id)
    if work is None or work.status != "processing":
        with context.complete():
            return
    try:
        source = _read(store, work.workspace_id, work.unlocked_sha256 or work.source_sha256)
        pdf = docx_to_pdf(gotenberg_url, source) if work.source_kind == "docx" else source
        prepared = prepare(pdf, max_pages=max_pages)
    except PasswordRequiredError:
        _needs_password(context, work)
    except TooManyPagesError as error:
        _fail(context, work, "too_many_pages", temporary=False, page_count=error.pages)
    except DamagedPdfError:
        code = "conversion_failed" if work.source_kind == "docx" else "damaged"
        _fail(context, work, code, temporary=False)
    except ConversionRefusedError:
        _fail(context, work, "conversion_failed", temporary=False)
    except Exception:  # anything else is retried; the last attempt fails the version
        log.warning("document.process_retry", version_id=str(work.id), attempt=context.attempt)
        if context.attempt < MAX_ATTEMPTS:
            raise
        _fail(context, work, "unavailable", temporary=True)
    else:
        _done(context, work, prepared, store)
