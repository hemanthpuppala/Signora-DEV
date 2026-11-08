"""Role descriptions and people-friendly default role names (Owner / Editor / Viewer copy).

Adds ``roles.description`` and renames the two default (system) roles of existing workspaces:
read_write -> Editor, read -> Viewer. Keys and permissions are unchanged.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied, not imported: a migration must keep meaning what it meant when it was written.
DEFAULTS = {
    "read_write": ("Editor", "Can create and send agreements, and rename the workspace."),
    "read": (
        "Viewer",
        "Can see projects, documents and signed agreements, but can't change anything.",
    ),
}
PREVIOUS = {"read_write": "Read/write", "read": "Read"}


def upgrade() -> None:
    op.add_column(
        "roles", sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False)
    )
    for key, (name, description) in DEFAULTS.items():
        op.execute(
            sa.text(
                "UPDATE roles SET name = :name, description = :description "
                "WHERE key = :key AND is_system"
            ).bindparams(name=name, description=description, key=key)
        )


def downgrade() -> None:
    for key, name in PREVIOUS.items():
        op.execute(
            sa.text("UPDATE roles SET name = :name WHERE key = :key AND is_system").bindparams(
                name=name, key=key
            )
        )
    op.drop_column("roles", "description")
