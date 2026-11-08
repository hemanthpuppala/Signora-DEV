"""Department countersigners: who may countersign, in default order (Phase 3 LLD topic 4).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "department_countersigners",
        sa.Column("department_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("added_by", UUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("position >= 1", name="position_positive"),
        sa.ForeignKeyConstraint(
            ["department_id", "workspace_id"],
            ["departments.id", "departments.workspace_id"],
            name=op.f("fk_department_countersigners_department_id_workspace_id_departments"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_department_countersigners_user_id_workspace_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["added_by"], ["users.id"], name=op.f("fk_department_countersigners_added_by_users")
        ),
        sa.PrimaryKeyConstraint(
            "department_id", "user_id", name=op.f("pk_department_countersigners")
        ),
        sa.UniqueConstraint(
            "department_id",
            "position",
            name=op.f("uq_department_countersigners_department_id_position"),
        ),
    )
    op.create_index(
        "ix_department_countersigners_user_id", "department_countersigners", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("department_countersigners")
