"""Which version is current (Phase 4 LLD §4.2; Phase 6 §1.3).

Only an approved version can be current: it is what new sends use. When a version is approved it
becomes current only if it is the newest approved version: no higher-numbered version is approved.
So approving an older version never takes over from a newer approved one, nor overrides a version a
person chose by hand. Decided under the document's row lock, so two approvals at once cannot both
win.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


def current_number(session: Session, document_id: uuid.UUID) -> int | None:
    """The current version's number, taking the document's row lock (None: no current version)."""
    session.execute(
        text("SELECT id FROM documents WHERE id = :d FOR NO KEY UPDATE"), {"d": document_id}
    )
    number: int | None = session.execute(
        text(
            "SELECT c.version_no FROM documents d "
            "JOIN document_versions c ON c.id = d.current_version_id WHERE d.id = :d"
        ),
        {"d": document_id},
    ).scalar_one_or_none()
    return number


def set_current(session: Session, document_id: uuid.UUID, version_id: uuid.UUID) -> None:
    session.execute(
        text("UPDATE documents SET current_version_id = :v, updated_at = now() WHERE id = :d"),
        {"d": document_id, "v": version_id},
    )


@dataclass(frozen=True)
class Promotion:
    promoted: bool
    previous: int | None  # the number that was current before (None: there was none)


def promote_if_newest(
    session: Session, document_id: uuid.UUID, version_id: uuid.UUID, version_no: int
) -> Promotion:
    """Make a newly approved version current unless a higher-numbered version is approved too."""
    previous = current_number(session, document_id)
    newer_approved = session.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM document_versions WHERE document_id = :d "
            "AND version_no > :n AND status = 'approved')"
        ),
        {"d": document_id, "n": version_no},
    ).scalar_one()
    if newer_approved:
        return Promotion(promoted=False, previous=previous)
    set_current(session, document_id, version_id)
    return Promotion(promoted=True, previous=previous)
