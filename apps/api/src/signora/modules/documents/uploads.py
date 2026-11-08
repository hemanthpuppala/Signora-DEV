"""Uploads: the first of two steps (Phase 4 LLD §2.2, ADR-DOC1).

The bytes arrive once, are checked (type from the contents, size) and stored in the blob store by
their SHA-256. The upload row then waits, for at most a day, to become a document or a version.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.blobstore import BlobStore
from signora.kernel.db import UnitOfWork
from signora.kernel.jobs import JobContext
from signora.modules.departments import get_department, load_access, require_active
from signora.modules.documents.domain import Kind, clean_filename, detect_kind
from signora.modules.identity_access import Actor, Permission

UPLOAD_TTL = timedelta(hours=24)
SWEEP = "sweep.uploads"


@dataclass(frozen=True)
class Upload:
    id: uuid.UUID
    department_id: uuid.UUID
    uploaded_by: uuid.UUID
    filename: str
    kind: Kind
    bytes: int
    sha256: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None


def authorize_upload(session: Session, actor: Actor, department_id: uuid.UUID) -> None:
    """Edit access in an active department of the actor's company (404, 409 or 403 otherwise)."""
    require_active(get_department(session, actor.workspace_id, department_id))
    load_access(session, actor).require(Permission.DOCUMENTS_SEND, department_id)


def store_upload(
    uow: UnitOfWork,
    *,
    actor: Actor,
    department_id: uuid.UUID,
    filename: str,
    path: Path,
    store: BlobStore,
    max_bytes: int,
) -> Upload:
    """Check the received file, store its bytes and record the upload."""
    kind = detect_kind(path)
    with path.open("rb") as data:
        ref = store.put(actor.workspace_id, data, max_bytes=max_bytes)
    row = uow.session.execute(
        text(
            "INSERT INTO uploads (workspace_id, department_id, uploaded_by, filename, kind, bytes, "
            "sha256, expires_at) VALUES (:w, :d, :u, :f, :k, :b, :h, "
            "now() + make_interval(secs => :ttl)) "
            "RETURNING id, department_id, uploaded_by, filename, kind, bytes, sha256, created_at, "
            "expires_at, used_at"
        ),
        {
            "w": actor.workspace_id,
            "d": department_id,
            "u": actor.user_id,
            "f": clean_filename(filename),
            "k": kind,
            "b": ref.size,
            "h": ref.sha256,
            "ttl": UPLOAD_TTL.total_seconds(),
        },
    ).one()
    return Upload(**row._mapping)


def sweep(context: JobContext) -> None:
    """Forget uploads past their day, used or not. Their blobs stay: a version may reference the
    same bytes, and blob clean-up is the hardening phase's locked pass (platform tracker P11)."""
    with context.complete() as uow:
        uow.session.execute(text("DELETE FROM uploads WHERE expires_at < now()"))
