"""Company wording in the Editor role's default description ("rename the company").

Only rows that still carry the exact previous default are changed, so a company that edited its own
description keeps it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "Can create and send agreements, and rename the workspace."
NEW = "Can create and send agreements, and rename the company."


def _replace(before: str, after: str) -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET description = :after "
            "WHERE key = 'read_write' AND is_system AND description = :before"
        ).bindparams(before=before, after=after)
    )


def upgrade() -> None:
    _replace(OLD, NEW)


def downgrade() -> None:
    _replace(NEW, OLD)
