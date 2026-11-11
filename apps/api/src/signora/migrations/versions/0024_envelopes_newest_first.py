"""An index for a department's envelopes, newest first (Phase 7 LLD §17).

The list reads a department's envelopes by sent time, newest first. Its index was (workspace,
department, status, sent_at), which orders them only within one state: the default list, with no
state chosen, read and sorted every envelope of the department for each page. This index gives
that order directly, with the id that breaks ties in the list's cursor.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_envelopes_workspace_id_department_id_sent_at_id"


def upgrade() -> None:
    op.create_index(INDEX, "envelopes", ["workspace_id", "department_id", "sent_at", "id"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="envelopes")
