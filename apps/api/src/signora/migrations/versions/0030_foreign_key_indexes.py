"""Index the foreign keys into rows the app deletes.

Deleting a row makes PostgreSQL check every foreign key pointing at it; without an index starting
with the referencing columns, each check reads the whole referencing table. A review save deletes
its version's fields and parties, so every field cost a scan of ``envelope_values`` and
``signing_drafts`` (and every party one of ``envelope_recipients``): a save of 2 000 fields grew
with those tables. Clearing old mail checked ``envelope_recipients.last_email_id`` the same way.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = (
    ("envelope_values", "field_id"),
    ("signing_drafts", "field_id"),
    ("envelope_recipients", "party_id"),
    ("envelope_recipients", "last_email_id"),
)


def upgrade() -> None:
    for table, column in INDEXES:
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def downgrade() -> None:
    for table, column in INDEXES:
        op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
