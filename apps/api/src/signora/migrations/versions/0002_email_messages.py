"""Email delivery records: email_messages (Phase 2 LLD §1a.4).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_messages",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("to_address", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'sent', 'failed')", name="status_valid"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.CheckConstraint(
            "status = 'queued' OR (text_body IS NULL AND html_body IS NULL)",
            name="final_has_no_body",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_messages")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_email_messages_dedupe_key")),
    )
    op.create_index(
        "ix_email_messages_status_created_at", "email_messages", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_email_messages_status_created_at", table_name="email_messages")
    op.drop_table("email_messages")
