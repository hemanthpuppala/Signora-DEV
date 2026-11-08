"""Department grants: edit access in one department (Phase 3 LLD topic 2).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "department_grants",
        sa.Column("department_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("granted_by", UUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["department_id", "workspace_id"],
            ["departments.id", "departments.workspace_id"],
            name=op.f("fk_department_grants_department_id_workspace_id_departments"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_department_grants_user_id_workspace_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"], ["users.id"], name=op.f("fk_department_grants_granted_by_users")
        ),
        sa.PrimaryKeyConstraint("department_id", "user_id", name=op.f("pk_department_grants")),
    )
    op.create_index("ix_department_grants_user_id", "department_grants", ["user_id"])


def downgrade() -> None:
    op.drop_table("department_grants")
