"""A version's life after processing, as the detection module drives it (Phase 5 LLD §1.1-1.3).

Processing (``processing.py``) leaves a version ``detecting`` and publishes
``DocumentVersionProcessed``. Detection reads the version through ``version_for_detection`` and ends
with ``finish_detection`` (ready, and current when it is the newest ready version) or
``fail_detection``. A person can start detection again with ``start_detection``. On a first version,
``apply_name_and_description`` writes what the AI proposed under Phase 4's rules (§1.3 there).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from signora.kernel.blobstore import BlobRef
from signora.kernel.db import UnitOfWork
from signora.kernel.errors import NotFound
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.departments import normalize_name
from signora.modules.documents.current import promote_if_newest
from signora.modules.documents.domain import DESCRIPTION_MAX, DETECTION_FAILURE_CODES, NAME_MAX
from signora.modules.documents.errors import (
    DocumentArchived,
    FieldsApproved,
    VersionNotApproved,
    VersionNotProcessed,
)
from signora.modules.documents.processing import publish_processed
from signora.modules.documents.service import (
    audit,
    changeable_version,
    get_document,
    lock_document,
    require_edit,
)
from signora.modules.identity_access import Actor


@dataclass(frozen=True)
class VersionForDetection:
    id: uuid.UUID
    workspace_id: uuid.UUID
    document_id: uuid.UUID
    version_no: int
    status: str
    source: BlobRef  # what detection reads (§2.1): the original PDF, or a Word file's converted PDF
    page_count: int
    ai_instructions: str
    document_name: str


def version_for_detection(session: Session, version_id: uuid.UUID) -> VersionForDetection | None:
    """The version's facts detection needs, or None when it no longer exists."""
    found = session.execute(
        text(
            "SELECT v.id, v.workspace_id, v.document_id, v.version_no, v.status, v.source_kind, "
            "v.source_sha256, v.source_bytes, v.unlocked_sha256, v.pdf_sha256, v.pdf_bytes, "
            "v.page_count, v.ai_instructions, d.name AS document_name FROM document_versions v "
            "JOIN documents d ON d.id = v.document_id WHERE v.id = :id"
        ),
        {"id": version_id},
    ).one_or_none()
    if found is None or found.pdf_sha256 is None:
        return None
    if found.source_kind == "pdf":
        # The original carries the form's formats and calculations, which the working copy no
        # longer has (§2.1). An unlocked copy's size is not recorded; the hash is the key.
        sha256 = found.unlocked_sha256 or found.source_sha256
        size = 0 if found.unlocked_sha256 else found.source_bytes
    else:  # a Word file: the PDF Gotenberg made from it (no scripts to lose)
        sha256, size = found.pdf_sha256, found.pdf_bytes
    return VersionForDetection(
        id=found.id,
        workspace_id=found.workspace_id,
        document_id=found.document_id,
        version_no=found.version_no,
        status=found.status,
        source=BlobRef(found.workspace_id, sha256, size),
        page_count=found.page_count,
        ai_instructions=found.ai_instructions,
        document_name=found.document_name,
    )


def require_document(session: Session, actor: Actor, document_id: uuid.UUID, *, edit: bool) -> None:
    """Everyone in the company may read a document; changing it needs edit access in its
    department. ``404`` for another company's document."""
    document = get_document(session, actor.workspace_id, document_id)
    if edit:
        require_edit(session, actor, document.department_id)


@dataclass(frozen=True)
class VersionForReview:
    """What review needs of a version (Phase 6 §6): its state, the size of each page as displayed
    (places are checked against it), and its name and description (a version made by editing takes
    them). Sending (Phase 7) also reads its document's name and department."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    department_id: uuid.UUID
    version_no: int
    status: str
    pages: list[tuple[float, float]]  # (width, height) in PDF points, rotation applied
    name: str | None
    description: str | None
    pdf: BlobRef | None  # the working copy the page shows; none until processed


def hold_document(session: Session, document_id: uuid.UUID) -> None:
    """The document's row lock, held until the transaction ends.

    A document, its versions and their fields change together, and the document's row is their
    one lock: whatever writes any of them takes it first (a person's change through
    ``documents.service.lock_document``, which also checks access; a Save, an Approve and the
    detection job's last step through this), and the audit chain's lock last. With one lock taken
    first by every writer, no two of them can each hold what the other waits for, whatever order
    they take the rows in after it. Taken later (an approval took it last, to move the current
    version; detection after writing the fields), two changes of one document could deadlock."""
    session.execute(
        text("SELECT id FROM documents WHERE id = :d FOR NO KEY UPDATE"), {"d": document_id}
    )


def version_for_review(
    session: Session,
    actor: Actor,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    edit: bool,
    lock: bool = False,
) -> VersionForReview:
    """A version of a document the actor may read (or, with ``edit``, change); ``404`` for one that
    is not this document's or this company's. ``lock`` takes the version's row lock, so a Save or
    an Approve decides on a state no one else is changing. An archived document's versions are
    read, never changed (Phase 4 §1.4). ``lock`` holds the document first (``hold_document``)."""
    if lock:
        hold_document(session, document_id)
    document = get_document(session, actor.workspace_id, document_id)
    if edit:
        require_edit(session, actor, document.department_id)
        if document.archived_at is not None:
            raise DocumentArchived
    row = session.execute(
        text(
            "SELECT id, workspace_id, document_id, version_no, status, pages, name, description, "
            "pdf_sha256, pdf_bytes "
            "FROM document_versions WHERE id = :v AND document_id = :d AND workspace_id = :w"
            + (" FOR UPDATE" if lock else "")
        ),
        {"v": version_id, "d": document_id, "w": actor.workspace_id},
    ).one_or_none()
    if row is None:
        raise NotFound
    return VersionForReview(
        id=row.id,
        workspace_id=row.workspace_id,
        document_id=row.document_id,
        document_name=document.name,
        department_id=document.department_id,
        version_no=row.version_no,
        status=row.status,
        pages=_page_sizes(row.pages),
        name=row.name,
        description=row.description,
        pdf=BlobRef(row.workspace_id, row.pdf_sha256, row.pdf_bytes)
        if row.pdf_sha256 is not None and row.pdf_bytes is not None
        else None,
    )


@dataclass(frozen=True)
class VersionForSigning:
    """A sent version as a signer's page reads it (Phase 8 §4): its working copy and page sizes.
    Signers have no Signora account: signing has already checked who they are."""

    id: uuid.UUID
    document_name: str
    version_no: int
    pdf: BlobRef  # the cleaned working copy: the only file ever shown in a page (topic 5 §5.2)
    pages: list[tuple[float, float]]


def version_for_signing(session: Session, version_id: uuid.UUID) -> VersionForSigning:
    row = session.execute(
        text(
            "SELECT v.id, v.workspace_id, v.version_no, v.pdf_sha256, v.pdf_bytes, v.pages, "
            "d.name AS document_name FROM document_versions v "
            "JOIN documents d ON d.id = v.document_id WHERE v.id = :id"
        ),
        {"id": version_id},
    ).one()  # a sent version is approved, processed and never deleted
    return VersionForSigning(
        id=row.id,
        document_name=row.document_name,
        version_no=row.version_no,
        pdf=BlobRef(row.workspace_id, row.pdf_sha256, row.pdf_bytes),
        pages=_page_sizes(row.pages),
    )


def _page_sizes(pages: list[dict[str, Any]] | None) -> list[tuple[float, float]]:
    return [(float(page["width"]), float(page["height"])) for page in pages or []]


def derived_name(source_name: str, source_no: int, source_derived: bool, version_no: int) -> str:
    """``"{source's name} - {n}"`` (§1.2). A source that was itself made by editing already ends
    in its own number, which the new one replaces: v6 "Financial NDA - 6" gives "Financial NDA - 7",
    not "Financial NDA - 6 - 7"."""
    suffix = f" - {source_no}"
    if source_derived and source_name.endswith(suffix):
        source_name = source_name.removesuffix(suffix)
    return f"{source_name} - {version_no}"


def derive_version(
    uow: UnitOfWork, *, actor: Actor, document_id: uuid.UUID, source_id: uuid.UUID
) -> VersionForReview:
    """The version an edit of an approved version becomes (Phase 6 §1.2): the next number, the
    same stored file and its facts (no upload, so no "already here" check), named after the source,
    with its description, recording where it came from, in review. Its fields are review's to
    write. Numbered under the document's row lock, as an upload is; the document and the source
    are each read once, and the new version is returned from what was written."""
    session = uow.session
    document = lock_document(session, actor, document_id)  # the number's lock; edit access
    if document.archived_at is not None:
        raise DocumentArchived
    source = session.execute(
        text(
            "SELECT workspace_id, version_no, status, name, description, pages, pdf_sha256, "
            "pdf_bytes, derived_from_version_id FROM document_versions "
            "WHERE id = :id AND document_id = :d"
        ),
        {"id": source_id, "d": document_id},
    ).one_or_none()
    if source is None:
        raise NotFound
    if source.status != "approved":
        raise VersionNotApproved
    version_no = document.latest_version_no + 1
    name = derived_name(
        source.name or document.name,
        source.version_no,
        source.derived_from_version_id is not None,
        version_no,
    )
    version_id: uuid.UUID = session.execute(
        text(
            "INSERT INTO document_versions (workspace_id, document_id, version_no, status, "
            "source_sha256, source_kind, source_filename, source_bytes, unlocked_sha256, "
            "pdf_sha256, pdf_bytes, page_count, pages, pages_without_text, ai_instructions, name, "
            "description, derived_from_version_id, uploaded_by, processed_at) "
            "SELECT workspace_id, document_id, :n, 'ready', source_sha256, source_kind, "
            "source_filename, source_bytes, unlocked_sha256, pdf_sha256, pdf_bytes, page_count, "
            "pages, pages_without_text, ai_instructions, :name, description, id, :by, now() "
            "FROM document_versions WHERE id = :source RETURNING id"
        ),
        {"n": version_no, "name": name, "by": actor.user_id, "source": source_id},
    ).scalar_one()
    audit(
        uow,
        actor,
        "document.version_derived",
        document_id,
        version_no=version_no,
        derived_from=source.version_no,
        name=name,
    )
    return VersionForReview(
        id=version_id,
        workspace_id=source.workspace_id,
        document_id=document_id,
        document_name=document.name,
        department_id=document.department_id,
        version_no=version_no,
        status="ready",
        pages=_page_sizes(source.pages),
        name=name,
        description=source.description,
        pdf=BlobRef(source.workspace_id, source.pdf_sha256, source.pdf_bytes)
        if source.pdf_sha256 is not None and source.pdf_bytes is not None
        else None,  # the same working copy
    )


def record_field_count(uow: UnitOfWork, version_id: uuid.UUID, field_count: int) -> None:
    """A version's field count after review saved its fields (Phase 6), for the lists."""
    uow.session.execute(
        text("UPDATE document_versions SET field_count = :n WHERE id = :id"),
        {"id": version_id, "n": field_count},
    )


def audit_document(
    uow: UnitOfWork, actor: Actor, action: str, document_id: uuid.UUID, **data: Any
) -> None:
    """Record a change to a document on the company's audit chain (one shape for every module)."""
    audit(uow, actor, action, document_id, **data)


def version_status(
    session: Session, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> str:
    """A version's status, for anyone in the company who may read the document; ``404`` for a
    version that is not this document's (or not this company's)."""
    require_document(session, actor, document_id, edit=False)
    status = session.execute(
        text(
            "SELECT status FROM document_versions WHERE id = :id AND document_id = :d "
            "AND workspace_id = :w"
        ),
        {"id": version_id, "d": document_id, "w": actor.workspace_id},
    ).scalar_one_or_none()
    if status is None:
        raise NotFound
    return str(status)


StartMode = Literal["resume", "restart", "running"]


def start_detection(
    uow: UnitOfWork, *, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> StartMode:
    """A person runs detection (§1.3): ``resume`` a failed run, ``restart`` a ready version from the
    beginning, or nothing while it is ``running``. Refused before processing has finished.

    It goes the way of every detection: the version is detecting and ``DocumentVersionProcessed``
    is published again, as Try again does, so each request is a new job (one path, never a job
    deduplicated away while the version waits). The caller resets the run first for a restart."""
    session = uow.session
    version = changeable_version(session, actor, document_id, version_id)
    if version.status == "detecting":
        return "running"
    if version.status == "approved":  # its fields are frozen (Phase 6 FR-R11)
        raise FieldsApproved
    if version.status == "failed" and version.failure_code in DETECTION_FAILURE_CODES:
        mode: StartMode = "resume"
    elif version.status == "ready":
        mode = "restart"
    else:
        raise VersionNotProcessed
    session.execute(
        text(
            "UPDATE document_versions SET status = 'detecting', failure_code = NULL, "
            "failure_temporary = false WHERE id = :id"
        ),
        {"id": version_id},
    )
    publish_processed(session, actor.workspace_id, document_id, version_id)
    audit(
        uow,
        actor,
        "document.detection_requested",
        document_id,
        version_no=version.version_no,
        mode=mode,
    )
    return mode


def _system_audit(uow: UnitOfWork, version: VersionForDetection, action: str, **data: Any) -> None:
    record(
        uow,
        chain=AuditChain.workspace(version.workspace_id),
        actor=AuditActor.system(),
        action=action,
        subject=Subject("document", version.document_id),
        data={"version_id": str(version.id), **data},
    )


def finish_detection(
    uow: UnitOfWork,
    version: VersionForDetection,
    *,
    field_count: int,
    name: str | None,
    description: str | None,
) -> bool:
    """The version is ready (§1.2 store): in review, with the name and description the AI wrote for
    it (none when nothing was asked). It becomes current only once approved (Phase 6 §1.3). False
    when it was no longer detecting (nothing changed)."""
    changed = uow.session.execute(
        text(
            "UPDATE document_versions SET status = 'ready', field_count = :n, name = :name, "
            "description = :description WHERE id = :id AND status = 'detecting' RETURNING id"
        ),
        {"id": version.id, "n": field_count, "name": name, "description": description},
    ).one_or_none()
    return changed is not None


def approve_version(
    uow: UnitOfWork,
    *,
    actor: Actor,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    details: Mapping[str, Any] | None = None,
) -> bool:
    """Approve a version in review (Phase 6 §1.3): frozen and sendable, recorded with who approved
    and when (and review's ``details``: the warnings accepted, the metrics); it becomes current
    when no higher-numbered version is approved (§4.2's rule, now over approved versions). False
    when it was not in review (nothing changed); the caller checks the revision and access first."""
    session = uow.session
    approved = session.execute(
        text(
            "UPDATE document_versions SET status = 'approved', approved_by = :by, "
            "approved_at = now() WHERE id = :id AND document_id = :d AND status = 'ready' "
            "RETURNING version_no"
        ),
        {"id": version_id, "d": document_id, "by": actor.user_id},
    ).scalar_one_or_none()
    if approved is None:
        return False
    audit(
        uow,
        actor,
        "document.version_approved",
        document_id,
        version_no=approved,
        **(details or {}),
    )
    promotion = promote_if_newest(session, document_id, version_id, approved)
    if promotion.promoted:
        audit(
            uow,
            actor,
            "document.current_version_changed",
            document_id,
            old=promotion.previous,
            new=approved,
            automatic=True,
        )
    return True


def fail_detection(uow: UnitOfWork, version: VersionForDetection, code: str) -> None:
    """A detection failure (§1.1): passing, so Try again is offered. Only while detecting.

    A version that already has fields (finding them again failed) goes back to ready with those
    fields: they are kept until a run stores new ones, and a ready version (perhaps the current
    one) never stops being usable because a second look failed. Detection keeps the failure on
    its run, so the person is told. A version without fields fails."""
    if code not in DETECTION_FAILURE_CODES:
        raise ValueError(f"not a detection failure: {code}")
    changed = uow.session.execute(
        text(
            "UPDATE document_versions SET "
            "status = CASE WHEN field_count IS NULL THEN 'failed' ELSE 'ready' END, "
            "failure_code = CASE WHEN field_count IS NULL THEN :code END, "
            "failure_temporary = field_count IS NULL "
            "WHERE id = :id AND status = 'detecting' RETURNING status"
        ),
        {"id": version.id, "code": code},
    ).scalar_one_or_none()
    if changed == "failed":
        _system_audit(uow, version, "document.version_failed", reason=code, temporary=True)
    elif changed == "ready":
        _system_audit(uow, version, "document.detection_failed", reason=code, kept_fields=True)


def apply_name_and_description(
    uow: UnitOfWork, version: VersionForDetection, *, name: str, description: str
) -> None:
    """What the AI proposed, under Phase 4 §1.3: the name only while it is still the one given at
    upload, valid and free in the department; the description only while nobody has written one.
    Each is written once (its source becomes ``ai``)."""
    session = uow.session
    current = session.execute(
        text(
            "SELECT name, name_source, description_source FROM documents "
            "WHERE id = :id FOR NO KEY UPDATE"
        ),
        {"id": version.document_id},
    ).one()
    proposed = normalize_name(name)
    if current.name_source == "upload" and 1 <= len(proposed) <= NAME_MAX:
        if proposed != current.name:
            try:
                with session.begin_nested():  # a taken name keeps the current one
                    session.execute(
                        text(
                            "UPDATE documents SET name = :n, name_source = 'ai', "
                            "updated_at = now() WHERE id = :id"
                        ),
                        {"id": version.document_id, "n": proposed},
                    )
                _system_audit(uow, version, "document.renamed", old=current.name, new=proposed)
            except IntegrityError:
                pass
        else:
            session.execute(
                text("UPDATE documents SET name_source = 'ai' WHERE id = :id"),
                {"id": version.document_id},
            )
    text_ = description.strip()
    if current.description_source == "none" and 0 < len(text_) <= DESCRIPTION_MAX:
        session.execute(
            text(
                "UPDATE documents SET description = :d, description_source = 'ai', "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": version.document_id, "d": text_},
        )
