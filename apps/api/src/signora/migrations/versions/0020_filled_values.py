"""Filled values on the page (Phase 7b LLD).

An envelope records the font its values are drawn in, kept as sent like its settings. Each text
place gains the size of the agreement's text beside it, measured when its version is approved, in a
table of its own keyed to the version: approved places are frozen, the sizes are derived from
them, and a draft's saves (which replace every place) never touch it.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEEP = """
    CREATE OR REPLACE FUNCTION envelopes_keep_what_was_sent() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF (NEW.workspace_id, NEW.department_id, NEW.document_id, NEW.version_id,
            NEW.require_email_code, NEW.reminder_interval_hours, NEW.max_reminders,
            NEW.notify_emails, NEW.sent_by, NEW.sent_at{font_new})
           IS DISTINCT FROM
           (OLD.workspace_id, OLD.department_id, OLD.document_id, OLD.version_id,
            OLD.require_email_code, OLD.reminder_interval_hours, OLD.max_reminders,
            OLD.notify_emails, OLD.sent_by, OLD.sent_at{font_old}) THEN
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
        sa.Column("font", sa.Text(), nullable=False, server_default=sa.text("'liberation-sans'")),
    )
    op.execute(_KEEP.format(font_new=", NEW.font", font_old=", OLD.font"))
    op.create_table(
        "placement_text_sizes",
        sa.Column("placement_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("size", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "size > 0 AND size <= 72", name=op.f("ck_placement_text_sizes_size_plausible")
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.id"],
            name=op.f("fk_placement_text_sizes_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("placement_id", name=op.f("pk_placement_text_sizes")),
    )
    op.create_index("ix_placement_text_sizes_version_id", "placement_text_sizes", ["version_id"])


def downgrade() -> None:
    op.drop_table("placement_text_sizes")
    op.execute(_KEEP.format(font_new="", font_old=""))
    op.drop_column("envelopes", "font")
