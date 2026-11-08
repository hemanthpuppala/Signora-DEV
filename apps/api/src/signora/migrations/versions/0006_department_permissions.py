"""Department permissions for the default Editor role, and users (id, workspace_id) key (Phase 3).

Adds departments.create, departments.manage, files.view_sends and files.send to each company's
default Editor role, but only where that role still holds exactly the previous default permissions
(a company that customised its Editor role keeps its own choice). Adds UNIQUE (id, workspace_id) on
users so department tables can check a referenced person belongs to the same company.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied, not imported: a migration keeps meaning what it meant when written.
PREVIOUS = ["members.directory", "workspace.rename"]
ADDED = ["departments.create", "departments.manage", "files.view_sends", "files.send"]


def upgrade() -> None:
    op.create_unique_constraint("uq_users_id_workspace_id", "users", ["id", "workspace_id"])
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || CAST(:added AS text[]) "
            "WHERE key = 'read_write' AND is_system "
            "AND permissions @> CAST(:previous AS text[]) "
            "AND permissions <@ CAST(:previous AS text[])"
        ).bindparams(added=ADDED, previous=PREVIOUS)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = CAST(:previous AS text[]) "
            "WHERE key = 'read_write' AND is_system "
            "AND permissions @> CAST(:all AS text[]) AND permissions <@ CAST(:all AS text[])"
        ).bindparams(previous=PREVIOUS, all=PREVIOUS + ADDED)
    )
    op.drop_constraint("uq_users_id_workspace_id", "users", type_="unique")
