"""Department wording in the Viewer role's default description (projects became departments).

Only rows that still carry the exact previous default are changed, so a company that edited its own
description keeps it.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "Can see projects, documents and signed agreements, but can't change anything."
NEW = "Can see departments, files and signed agreements, but can't change anything."


def _replace(before: str, after: str) -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET description = :after "
            "WHERE key = 'read' AND is_system AND description = :before"
        ).bindparams(before=before, after=after)
    )


def upgrade() -> None:
    _replace(OLD, NEW)


def downgrade() -> None:
    _replace(NEW, OLD)
