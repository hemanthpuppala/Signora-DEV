"""A signature never covers the agreement's text above it: the room above each signature or
initials place, measured from the PDF at approval (``placement_mark_tops``). Versions approved
before are measured by ``signora measure-text-sizes``; until then the full height is used.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "placement_mark_tops",
        sa.Column("placement_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("top", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.id"],
            name=op.f("fk_placement_mark_tops_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("placement_id", name=op.f("pk_placement_mark_tops")),
    )
    op.create_index("ix_placement_mark_tops_version_id", "placement_mark_tops", ["version_id"])


def downgrade() -> None:
    op.drop_table("placement_mark_tops")
