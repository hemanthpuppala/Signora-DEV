"""Files are called documents (Phase 4 LLD §1.6): permission names and the Viewer description.

``files.view_sends`` and ``files.send`` become ``documents.view_sends`` and ``documents.send`` in
every role that holds them, default or customised, so nobody gains or loses access. The Viewer
role's default description is reworded only where it still carries the exact previous default, so
a company that wrote its own keeps it.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied, not imported: a migration keeps meaning what it meant when written.
RENAMES = [("files.view_sends", "documents.view_sends"), ("files.send", "documents.send")]
OLD_VIEWER = "Can see departments, files and signed agreements, but can't change anything."
NEW_VIEWER = "Can see departments, documents and signed agreements, but can't change anything."


def _rename(before: str, after: str) -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = array_replace(permissions, :before, :after) "
            "WHERE :before = ANY(permissions)"
        ).bindparams(before=before, after=after)
    )


def _viewer(before: str, after: str) -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET description = :after "
            "WHERE key = 'read' AND is_system AND description = :before"
        ).bindparams(before=before, after=after)
    )


def upgrade() -> None:
    for old, new in RENAMES:
        _rename(old, new)
    _viewer(OLD_VIEWER, NEW_VIEWER)


def downgrade() -> None:
    for old, new in RENAMES:
        _rename(new, old)
    _viewer(NEW_VIEWER, OLD_VIEWER)
