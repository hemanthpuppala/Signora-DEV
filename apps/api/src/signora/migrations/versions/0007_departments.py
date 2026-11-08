"""Departments (Phase 3 LLD topic 1).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", UUID, nullable=True),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name_length"),
        sa.CheckConstraint("char_length(description) <= 500", name="description_length"),
        sa.CheckConstraint(
            "(archived_at IS NULL) = (archived_by IS NULL)", name="archived_together"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_departments_workspace_id_workspaces")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_departments_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["archived_by"], ["users.id"], name=op.f("fk_departments_archived_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint("id", "workspace_id", name=op.f("uq_departments_id_workspace_id")),
    )
    op.create_index(
        "uq_departments_active_name",
        "departments",
        ["workspace_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "ix_departments_workspace_created",
        "departments",
        ["workspace_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("departments")
