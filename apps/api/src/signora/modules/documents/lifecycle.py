"""A version's life after processing, as the detection module drives it (Phase 5 LLD §1.1-1.3).

Processing (``processing.py``) leaves a version ``detecting`` and publishes
``DocumentVersionProcessed``. Detection reads the version through ``version_for_detection`` and ends
with ``finish_detection`` (ready, and current when it is the newest ready version) or
``fail_detection``. A person can start detection again with ``start_detection``. On a first version,
``apply_name_and_description`` writes what the AI proposed under Phase 4's rules (§1.3 there).
"""

from __future__ import annotations

import uuid
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
from signora.modules.documents.errors import VersionNotProcessed
from signora.modules.documents.service import (
    audit,
    changeable_version,
    get_document,
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
    write_name_and_description: bool  # Phase 4 §1.3: until a person or the AI has written them


def version_for_detection(session: Session, version_id: uuid.UUID) -> VersionForDetection | None:
    """The version's facts detection needs, or None when it no longer exists."""
    found = session.execute(
        text(
            "SELECT v.id, v.workspace_id, v.document_id, v.version_no, v.status, v.source_kind, "
            "v.source_sha256, v.source_bytes, v.unlocked_sha256, v.pdf_sha256, v.pdf_bytes, "
            "v.page_count, v.ai_instructions, d.name AS document_name, d.name_source, "
            "d.description_source FROM document_versions v "
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
        write_name_and_description=found.name_source == "upload"
        or found.description_source == "none",
    )


def require_document(session: Session, actor: Actor, document_id: uuid.UUID, *, edit: bool) -> None:
    """Everyone in the company may read a document; changing it needs edit access in its
    department. ``404`` for another company's document."""
    document = get_document(session, actor.workspace_id, document_id)
    if edit:
        require_edit(session, actor, document.department_id)


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
    beginning, or nothing while it is ``running``. Refused before processing has finished."""
    session = uow.session
    version = changeable_version(session, actor, document_id, version_id)
    if version.status == "detecting":
        return "running"
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


def finish_detection(uow: UnitOfWork, version: VersionForDetection, *, field_count: int) -> bool:
    """The version is ready (§1.2 store); it becomes current when no higher-numbered version is
    ready (Phase 4 §4.2). False when it was no longer detecting (nothing changed)."""
    changed = uow.session.execute(
        text(
            "UPDATE document_versions SET status = 'ready', field_count = :n "
            "WHERE id = :id AND status = 'detecting' RETURNING id"
        ),
        {"id": version.id, "n": field_count},
    ).one_or_none()
    if changed is None:
        return False
    promotion = promote_if_newest(uow.session, version.document_id, version.id, version.version_no)
    if promotion.promoted:
        _system_audit(
            uow,
            version,
            "document.current_version_changed",
            old=promotion.previous,
            new=version.version_no,
            automatic=True,
        )
    return True


def fail_detection(uow: UnitOfWork, version: VersionForDetection, code: str) -> None:
    """A detection failure (§1.1): passing, so Try again is offered. Only while detecting."""
    if code not in DETECTION_FAILURE_CODES:
        raise ValueError(f"not a detection failure: {code}")
    changed = uow.session.execute(
        text(
            "UPDATE document_versions SET status = 'failed', failure_code = :code, "
            "failure_temporary = true WHERE id = :id AND status = 'detecting' RETURNING id"
        ),
        {"id": version.id, "code": code},
    ).one_or_none()
    if changed is not None:
        _system_audit(uow, version, "document.version_failed", reason=code, temporary=True)


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
