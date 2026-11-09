"""A version's own name (Phase 5 LLD §6.5): what the AI called it.

Every detection now asks the AI for the agreement's name and description; the version keeps both
(``ai_name``, and the existing ``ai_description``), so its card can show what it is instead of its
file name. Versions already detected take them from their run's stored proposal.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_versions", sa.Column("ai_name", sa.Text(), nullable=True))
    op.execute(
        "UPDATE document_versions v SET "
        "ai_name = NULLIF(r.result -> 'document' ->> 'name', ''), "
        "ai_description = NULLIF(r.result -> 'document' ->> 'description', '') "
        "FROM detection_runs r WHERE r.version_id = v.id AND r.result IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("document_versions", "ai_name")
