"""Which version is current (Phase 4 LLD §4.2).

Only a ready version can be current. When a version becomes ready it becomes current unless a
higher-numbered version already is, so a slow version 3 never takes over from version 4. Decided
under the document's row lock, so two versions finishing at once cannot both win.
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
    """Make a newly ready version current unless a higher-numbered one already is."""
    previous = current_number(session, document_id)
    if previous is not None and previous > version_no:
        return Promotion(promoted=False, previous=previous)
    set_current(session, document_id, version_id)
    return Promotion(promoted=True, previous=previous)
