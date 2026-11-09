"""Documents and their versions (Phase 4 LLD topics 1, 2 and 4).

Every query is scoped to the actor's company. Reading needs only membership of the company;
changing needs edit access in the document's department, and an active department and document.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from signora.kernel.blobstore import BlobRef, BlobStore
from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, NotFound, RateLimited, ValidationFailed
from signora.kernel.ratelimit import RateLimiter
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.departments import get_department, load_access, normalize_name, require_active
from signora.modules.documents.current import current_number, set_current
from signora.modules.documents.domain import (
    AI_INSTRUCTIONS_MAX,
    DESCRIPTION_MAX,
    DETECTION_FAILURE_CODES,
    NAME_MAX,
    Kind,
)
from signora.modules.documents.errors import (
    CannotRetry,
    DocumentArchived,
    DocumentNameTaken,
    DuplicateFile,
    NotLocked,
    UploadNotFound,
    UploadUsed,
    VersionNotReady,
    WrongPassword,
)
from signora.modules.documents.pdf import unlock
from signora.modules.documents.processing import enqueue_processing, publish_processed
from signora.modules.identity_access import Actor, Permission

ACTIVE_NAME_INDEX = "uq_documents_active_name"
UNLOCK_TRIES = 5  # wrong passwords per version (§2.6)
UNLOCK_WINDOW = timedelta(minutes=15)


@dataclass(frozen=True)
class DocumentRow:
    id: uuid.UUID
    department_id: uuid.UUID
    name: str
    description: str
    require_email_code: bool
    current_version_id: uuid.UUID | None
    created_by_id: uuid.UUID
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    # The current version's facts and the newest version's state, for lists (topic 6).
    current_version_no: int | None
    current_kind: Kind | None
    current_page_count: int | None
    latest_version_id: uuid.UUID
    latest_version_no: int
    latest_status: str
    latest_created_at: datetime
    latest_field_count: int | None


@dataclass(frozen=True)
class VersionRow:
    id: uuid.UUID
    document_id: uuid.UUID
    version_no: int
    status: str
    failure_code: str | None
    failure_temporary: bool
    source_kind: Kind
    source_filename: str
    source_bytes: int
    source_sha256: str
    pdf_sha256: str | None
    pdf_bytes: int | None
    page_count: int | None
    pages: list[dict[str, Any]] | None
    pages_without_text: list[int]
    ai_instructions: str
    uploaded_by_id: uuid.UUID
    uploaded_by_name: str
    created_at: datetime
    processed_at: datetime | None
    field_count: int | None
    ai_name: str | None
    ai_description: str | None


@dataclass(frozen=True)
class Duplicate:
    document_id: uuid.UUID
    document_name: str
    version_no: int
    archived: bool


_DOCUMENT_SELECT = """
    SELECT d.id, d.department_id, d.name, d.description, d.require_email_code,
           d.current_version_id, d.created_by AS created_by_id, u.name AS created_by_name,
           d.created_at, d.updated_at, d.archived_at,
           c.version_no AS current_version_no, c.source_kind AS current_kind,
           c.page_count AS current_page_count,
           l.id AS latest_version_id, l.version_no AS latest_version_no, l.status AS latest_status,
           l.created_at AS latest_created_at, l.field_count AS latest_field_count
    FROM documents d
    JOIN users u ON u.id = d.created_by
    LEFT JOIN document_versions c ON c.id = d.current_version_id
    JOIN LATERAL (
        SELECT id, version_no, status, created_at, field_count FROM document_versions
        WHERE document_id = d.id ORDER BY version_no DESC LIMIT 1
    ) l ON true
    WHERE d.workspace_id = :w
"""

_VERSION_SELECT = """
    SELECT v.id, v.document_id, v.version_no, v.status, v.failure_code, v.failure_temporary,
           v.source_kind, v.source_filename, v.source_bytes, v.source_sha256, v.pdf_sha256,
           v.pdf_bytes, v.page_count, v.pages, v.pages_without_text, v.ai_instructions,
           v.uploaded_by AS uploaded_by_id, u.name AS uploaded_by_name, v.created_at,
           v.processed_at, v.field_count, v.ai_name, v.ai_description
    FROM document_versions v JOIN users u ON u.id = v.uploaded_by
    WHERE v.workspace_id = :w
"""


# --- reading -------------------------------------------------------------------------------


def get_document(session: Session, workspace_id: uuid.UUID, document_id: uuid.UUID) -> DocumentRow:
    """The company's document, or ``404`` (also for another company's id)."""
    found = session.execute(
        text(_DOCUMENT_SELECT + " AND d.id = :id"), {"w": workspace_id, "id": document_id}
    ).one_or_none()
    if found is None:
        raise NotFound
    return DocumentRow(**found._mapping)


def list_documents(
    session: Session, workspace_id: uuid.UUID, department_id: uuid.UUID, *, archived: bool
) -> list[DocumentRow]:
    get_department(session, workspace_id, department_id)  # 404 for another company's id
    rows = session.execute(
        text(
            _DOCUMENT_SELECT + " AND d.department_id = :d AND (d.archived_at IS NOT NULL) = :a "
            "ORDER BY lower(d.name), d.id"
        ),
        {"w": workspace_id, "d": department_id, "a": archived},
    )
    return [DocumentRow(**row._mapping) for row in rows]


def list_versions(
    session: Session, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> list[VersionRow]:
    rows = session.execute(
        text(_VERSION_SELECT + " AND v.document_id = :d ORDER BY v.version_no DESC"),
        {"w": workspace_id, "d": document_id},
    )
    return [VersionRow(**row._mapping) for row in rows]


def get_version(
    session: Session, workspace_id: uuid.UUID, document_id: uuid.UUID, version_id: uuid.UUID
) -> VersionRow:
    found = session.execute(
        text(_VERSION_SELECT + " AND v.document_id = :d AND v.id = :id"),
        {"w": workspace_id, "d": document_id, "id": version_id},
    ).one_or_none()
    if found is None:
        raise NotFound
    return VersionRow(**found._mapping)


def find_duplicate(
    session: Session, workspace_id: uuid.UUID, department_id: uuid.UUID, sha256: str
) -> Duplicate | None:
    """The first version in the department with these exact bytes (topic 2 §2.3)."""
    found = session.execute(
        text(
            "SELECT d.id AS document_id, d.name AS document_name, v.version_no, "
            "d.archived_at IS NOT NULL AS archived "
            "FROM document_versions v JOIN documents d ON d.id = v.document_id "
            "WHERE v.workspace_id = :w AND v.source_sha256 = :h AND d.department_id = :d "
            "ORDER BY d.archived_at IS NOT NULL, v.created_at LIMIT 1"
        ),
        {"w": workspace_id, "h": sha256, "d": department_id},
    ).one_or_none()
    return Duplicate(**found._mapping) if found is not None else None


# --- checks --------------------------------------------------------------------------------


def require_edit(session: Session, actor: Actor, department_id: uuid.UUID) -> None:
    """Edit access in an active department (``409 department-archived``, ``403``)."""
    require_active(get_department(session, actor.workspace_id, department_id))
    load_access(session, actor).require(Permission.DOCUMENTS_SEND, department_id)


def _valid_name(raw: str) -> str:
    name = normalize_name(raw)
    if not name:
        raise ValidationFailed([FieldError("name", "Enter a name")])
    if len(name) > NAME_MAX:
        raise ValidationFailed([FieldError("name", f"Use {NAME_MAX} or fewer characters")])
    return name


def _valid_text(field: str, raw: str, limit: int) -> str:
    value = raw.strip()
    if len(value) > limit:
        raise ValidationFailed([FieldError(field, f"Use {limit} or fewer characters")])
    return value


def _name_taken(error: IntegrityError) -> bool:
    return ACTIVE_NAME_INDEX in str(error.orig)


def audit(uow: UnitOfWork, actor: Actor, action: str, document_id: uuid.UUID, **data: Any) -> None:
    """Record a change to a document on the company's audit chain."""
    record(
        uow,
        chain=AuditChain.workspace(actor.workspace_id),
        actor=AuditActor("user", actor.user_id, actor.email),
        action=action,
        subject=Subject("document", document_id),
        data=data,
    )


@dataclass(frozen=True)
class _Taken:
    filename: str
    kind: Kind
    bytes: int
    sha256: str


def _take_upload(
    session: Session, actor: Actor, upload_id: uuid.UUID, department_id: uuid.UUID
) -> _Taken:
    """Mark the actor's upload for this department as used, once (``404``/``409`` otherwise)."""
    found = session.execute(
        text(
            "SELECT filename, kind, bytes, sha256, used_at FROM uploads "
            "WHERE id = :id AND workspace_id = :w AND department_id = :d AND uploaded_by = :u "
            "AND expires_at > now() FOR UPDATE"
        ),
        {"id": upload_id, "w": actor.workspace_id, "d": department_id, "u": actor.user_id},
    ).one_or_none()
    if found is None:
        raise UploadNotFound
    if found.used_at is not None:
        raise UploadUsed
    session.execute(text("UPDATE uploads SET used_at = now() WHERE id = :id"), {"id": upload_id})
    return _Taken(found.filename, found.kind, found.bytes, found.sha256)


def _duplicate_detail(duplicate: Duplicate) -> str:
    archived = " (archived)" if duplicate.archived else ""
    return f"Already here as {duplicate.document_name}{archived}, version {duplicate.version_no}"


def _insert_version(
    session: Session,
    actor: Actor,
    document_id: uuid.UUID,
    version_no: int,
    upload: _Taken,
    ai_instructions: str,
) -> uuid.UUID:
    version_id: uuid.UUID = session.execute(
        text(
            "INSERT INTO document_versions (workspace_id, document_id, version_no, source_sha256, "
            "source_kind, source_filename, source_bytes, ai_instructions, uploaded_by) "
            "VALUES (:w, :d, :n, :h, :k, :f, :b, :i, :u) RETURNING id"
        ),
        {
            "w": actor.workspace_id,
            "d": document_id,
            "n": version_no,
            "h": upload.sha256,
            "k": upload.kind,
            "f": upload.filename,
            "b": upload.bytes,
            "i": ai_instructions,
            "u": actor.user_id,
        },
    ).scalar_one()
    return version_id


# --- changing ------------------------------------------------------------------------------


def create_document(
    uow: UnitOfWork,
    *,
    actor: Actor,
    department_id: uuid.UUID,
    name: str,
    ai_instructions: str,
    upload_id: uuid.UUID,
    allow_duplicate: bool,
) -> tuple[DocumentRow, uuid.UUID]:
    """A document with its first version (processing). Returns the document and the version id.

    The same bytes already in the department need ``allow_duplicate`` (the person confirmed a
    separate document, §2.3); they never become a version.
    """
    session = uow.session
    require_edit(session, actor, department_id)
    clean_name = _valid_name(name)
    instructions = _valid_text("ai_instructions", ai_instructions, AI_INSTRUCTIONS_MAX)
    upload = _take_upload(session, actor, upload_id, department_id)
    duplicate = find_duplicate(session, actor.workspace_id, department_id, upload.sha256)
    if duplicate is not None and not allow_duplicate:
        raise DuplicateFile(_duplicate_detail(duplicate))
    try:
        with session.begin_nested():  # a taken name rolls back only this insert
            document_id: uuid.UUID = session.execute(
                text(
                    "INSERT INTO documents (workspace_id, department_id, name, created_by) "
                    "VALUES (:w, :d, :n, :u) RETURNING id"
                ),
                {"w": actor.workspace_id, "d": department_id, "n": clean_name, "u": actor.user_id},
            ).scalar_one()
    except IntegrityError as error:
        if _name_taken(error):
            raise DocumentNameTaken from None
        raise
    version_id = _insert_version(session, actor, document_id, 1, upload, instructions)
    enqueue_processing(session, version_id)
    audit(uow, actor, "document.created", document_id, name=clean_name)
    audit(
        uow,
        actor,
        "document.version_added",
        document_id,
        version_no=1,
        filename=upload.filename,
        sha256=upload.sha256,
    )
    return get_document(session, actor.workspace_id, document_id), version_id


def _lock_document(session: Session, actor: Actor, document_id: uuid.UUID) -> DocumentRow:
    """The document under its row lock (version numbers, name changes), for changing."""
    locked = session.execute(
        text("SELECT id FROM documents WHERE id = :id AND workspace_id = :w FOR NO KEY UPDATE"),
        {"id": document_id, "w": actor.workspace_id},
    ).one_or_none()
    if locked is None:
        raise NotFound
    document = get_document(session, actor.workspace_id, document_id)
    require_edit(session, actor, document.department_id)
    return document


def add_version(
    uow: UnitOfWork,
    *,
    actor: Actor,
    document_id: uuid.UUID,
    ai_instructions: str,
    upload_id: uuid.UUID,
) -> uuid.UUID:
    """The next version (processing). The same bytes as any version in the department are
    refused: they can only ever become a separate document (§2.3)."""
    session = uow.session
    document = _lock_document(session, actor, document_id)
    if document.archived_at is not None:
        raise DocumentArchived
    instructions = _valid_text("ai_instructions", ai_instructions, AI_INSTRUCTIONS_MAX)
    upload = _take_upload(session, actor, upload_id, document.department_id)
    duplicate = find_duplicate(session, actor.workspace_id, document.department_id, upload.sha256)
    if duplicate is not None:
        raise DuplicateFile(_duplicate_detail(duplicate))
    version_no = document.latest_version_no + 1  # under the document lock: never shared
    version_id = _insert_version(session, actor, document_id, version_no, upload, instructions)
    enqueue_processing(session, version_id)
    audit(
        uow,
        actor,
        "document.version_added",
        document_id,
        version_no=version_no,
        filename=upload.filename,
        sha256=upload.sha256,
    )
    return version_id


def update_document(
    uow: UnitOfWork,
    *,
    actor: Actor,
    document_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    require_email_code: bool | None = None,
) -> DocumentRow:
    """A person's change: their name or description is never replaced by the AI (topic 1)."""
    session = uow.session
    current = _lock_document(session, actor, document_id)
    if current.archived_at is not None:
        raise DocumentArchived
    assignments: list[str] = []
    values: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []
    if name is not None and (new_name := _valid_name(name)) != current.name:
        assignments.append("name = :name, name_source = 'person'")
        values["name"] = new_name
        events.append(("document.renamed", {"old": current.name, "new": new_name, "by": "person"}))
    if (
        description is not None
        and (new_description := _valid_text("description", description, DESCRIPTION_MAX))
        != current.description
    ):
        assignments.append("description = :description, description_source = 'person'")
        values["description"] = new_description
        events.append(("document.description_changed", {"by": "person"}))
    if require_email_code is not None and require_email_code != current.require_email_code:
        assignments.append("require_email_code = :code")
        values["code"] = require_email_code
        events.append(("document.email_code_changed", {"require_email_code": require_email_code}))
    if not assignments:
        return current
    try:
        with session.begin_nested():
            session.execute(
                text(
                    f"UPDATE documents SET {', '.join(assignments)}, updated_at = now() "  # noqa: S608 - fixed fragments
                    "WHERE id = :id AND workspace_id = :w"
                ),
                {"id": document_id, "w": actor.workspace_id, **values},
            )
    except IntegrityError as error:
        if _name_taken(error):
            raise DocumentNameTaken from None
        raise
    for action, data in events:
        audit(uow, actor, action, document_id, **data)
    return get_document(session, actor.workspace_id, document_id)


def archive_document(uow: UnitOfWork, *, actor: Actor, document_id: uuid.UUID) -> DocumentRow:
    """Repeat-safe: archiving an archived document returns it unchanged."""
    session = uow.session
    _lock_document(session, actor, document_id)
    changed = session.execute(
        text(
            "UPDATE documents SET archived_at = now(), archived_by = :u, updated_at = now() "
            "WHERE id = :id AND archived_at IS NULL RETURNING id"
        ),
        {"id": document_id, "u": actor.user_id},
    ).one_or_none()
    if changed is not None:
        audit(uow, actor, "document.archived", document_id)
    return get_document(session, actor.workspace_id, document_id)


def restore_document(uow: UnitOfWork, *, actor: Actor, document_id: uuid.UUID) -> DocumentRow:
    """Repeat-safe; ``409 document-name-taken`` when an active document now has the name."""
    session = uow.session
    _lock_document(session, actor, document_id)
    try:
        with session.begin_nested():
            changed = session.execute(
                text(
                    "UPDATE documents SET archived_at = NULL, archived_by = NULL, "
                    "updated_at = now() WHERE id = :id AND archived_at IS NOT NULL RETURNING id"
                ),
                {"id": document_id},
            ).one_or_none()
    except IntegrityError as error:
        if _name_taken(error):
            raise DocumentNameTaken(
                "An active document in this department now has this name. Rename that one first"
            ) from None
        raise
    if changed is not None:
        audit(uow, actor, "document.restored", document_id)
    return get_document(session, actor.workspace_id, document_id)


def changeable_version(
    session: Session, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> VersionRow:
    document = _lock_document(session, actor, document_id)
    if document.archived_at is not None:
        raise DocumentArchived
    return get_version(session, actor.workspace_id, document_id, version_id)


def retry_version(
    uow: UnitOfWork, *, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> None:
    """ "Try again" after a passing failure outlasted its retries (§3.4). Repeat-safe. A detection
    failure goes back to detecting and detection resumes where it stopped (Phase 5 §1.2)."""
    session = uow.session
    version = changeable_version(session, actor, document_id, version_id)
    if version.status in ("processing", "detecting"):
        return
    if version.status != "failed" or not version.failure_temporary:
        raise CannotRetry
    if version.failure_code in DETECTION_FAILURE_CODES:
        session.execute(
            text(
                "UPDATE document_versions SET status = 'detecting', failure_code = NULL, "
                "failure_temporary = false WHERE id = :id"
            ),
            {"id": version_id},
        )
        publish_processed(session, actor.workspace_id, document_id, version_id)
        audit(uow, actor, "document.version_retried", document_id, version_no=version.version_no)
        return
    session.execute(
        text(
            "UPDATE document_versions SET status = 'processing', failure_code = NULL, "
            "failure_temporary = false WHERE id = :id"
        ),
        {"id": version_id},
    )
    enqueue_processing(session, version_id)
    audit(uow, actor, "document.version_retried", document_id, version_no=version.version_no)


def unlock_version(
    uow: UnitOfWork,
    *,
    actor: Actor,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    password: str,
    store: BlobStore,
    limiter: RateLimiter,
) -> None:
    """Open a password-protected PDF (§2.6). The password is tried once and never stored, logged
    or audited; an unlocked copy becomes the source processing continues from."""
    session = uow.session
    version = changeable_version(session, actor, document_id, version_id)
    if version.status != "needs_password":
        raise NotLocked
    key = f"documents.unlock:{version_id}"
    if (retry := limiter.check(key, limit=UNLOCK_TRIES, window=UNLOCK_WINDOW)) is not None:
        raise RateLimited(retry)
    source = BlobRef(actor.workspace_id, version.source_sha256, version.source_bytes)
    with store.open(source) as handle:
        unlocked = unlock(handle.read(), password)
    if unlocked is None:
        limiter.hit(key, limit=UNLOCK_TRIES, window=UNLOCK_WINDOW)
        raise WrongPassword
    ref = store.put(actor.workspace_id, BytesIO(unlocked), max_bytes=len(unlocked))
    session.execute(
        text(
            "UPDATE document_versions SET unlocked_sha256 = :h, status = 'processing' "
            "WHERE id = :id AND status = 'needs_password'"
        ),
        {"id": version_id, "h": ref.sha256},
    )
    enqueue_processing(session, version_id)
    audit(uow, actor, "document.version_unlocked", document_id, version_no=version.version_no)


def make_current(
    uow: UnitOfWork, *, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> None:
    """A person chooses which ready version new sends use (§4.2; the screen asks first).
    Repeat-safe. A later upload that becomes ready takes over again."""
    session = uow.session
    version = changeable_version(session, actor, document_id, version_id)
    if version.status != "ready":
        raise VersionNotReady
    previous = current_number(session, document_id)
    if previous == version.version_no:
        return
    set_current(session, document_id, version_id)
    audit(
        uow,
        actor,
        "document.current_version_changed",
        document_id,
        old=previous,
        new=version.version_no,
        automatic=False,
    )
