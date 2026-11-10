"""An envelope's time zone (Phase 7b): the sender's, recorded at send, so its emails give its
dates as the sender sees them in the app ("Nov 23, 2026 at 8:05 PM PST"), not in UTC. Kept as
sent, with its other settings. Envelopes sent before take UTC.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEEP = """
    CREATE OR REPLACE FUNCTION envelopes_keep_what_was_sent() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF (NEW.workspace_id, NEW.department_id, NEW.document_id, NEW.version_id,
            NEW.require_email_code, NEW.reminder_interval_hours, NEW.max_reminders,
            NEW.notify_emails, NEW.sent_by, NEW.sent_at, NEW.font{zone_new})
           IS DISTINCT FROM
           (OLD.workspace_id, OLD.department_id, OLD.document_id, OLD.version_id,
            OLD.require_email_code, OLD.reminder_interval_hours, OLD.max_reminders,
            OLD.notify_emails, OLD.sent_by, OLD.sent_at, OLD.font{zone_old}) THEN
            RAISE EXCEPTION 'what an envelope sent cannot change'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
"""


def upgrade() -> None:
    op.add_column(
        "envelopes",
        sa.Column("time_zone", sa.Text(), nullable=False, server_default=sa.text("'UTC'")),
    )
    op.execute(_KEEP.format(zone_new=", NEW.time_zone", zone_old=", OLD.time_zone"))


def downgrade() -> None:
    op.execute(_KEEP.format(zone_new="", zone_old=""))
    op.drop_column("envelopes", "time_zone")
