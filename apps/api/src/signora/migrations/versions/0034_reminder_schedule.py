"""Automatic reminders (reminders LLD §6): the sweep finds due people by an index of the live
schedules, and everyone still to act on an envelope already out is reminded one interval from now
(not all at once on the deploy), under the rule ``envelopes.schedule`` applies.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_envelope_recipients_next_reminder_at",
        "envelope_recipients",
        ["next_reminder_at"],
        postgresql_where=sa.text("next_reminder_at IS NOT NULL"),
    )
    op.execute(
        "UPDATE envelope_recipients r SET next_reminder_at = "
        "now() + make_interval(hours => e.reminder_interval_hours) FROM envelopes e "
        "WHERE e.id = r.envelope_id AND r.status IN ('sent', 'opened', 'viewed') "
        "AND e.status IN ('sent', 'opened', 'viewed', 'signed') "
        "AND r.reminders_sent < e.max_reminders "
        "AND now() + make_interval(hours => e.reminder_interval_hours) < e.expires_at"
    )


def downgrade() -> None:
    op.execute("UPDATE envelope_recipients SET next_reminder_at = NULL")
    op.drop_index("ix_envelope_recipients_next_reminder_at", table_name="envelope_recipients")
