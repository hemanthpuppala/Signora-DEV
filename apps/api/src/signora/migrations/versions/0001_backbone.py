"""Backbone tables: jobs, idempotency_keys, audit_events (backbone LLD topics 2, 3.5, 4.6).

Revision ID: 0001
Revises:
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPTY_JSON = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", pg.JSONB(), server_default=EMPTY_JSON, nullable=False),
        sa.Column("meta", pg.JSONB(), server_default=EMPTY_JSON, nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'dead')", name="status_valid"
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_jobs_dedupe_key")),
    )
    op.create_index(
        "ix_jobs_due", "jobs", ["run_at"], postgresql_where=sa.text("status = 'queued'")
    )
    op.create_index(
        "ix_jobs_lease",
        "jobs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_jobs_finished",
        "jobs",
        ["finished_at"],
        postgresql_where=sa.text("status = 'succeeded'"),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", pg.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("char_length(key) BETWEEN 1 AND 255", name="key_length"),
        sa.CheckConstraint("octet_length(request_hash) = 32", name="request_hash_sha256"),
        sa.PrimaryKeyConstraint("scope", "key", name=op.f("pk_idempotency_keys")),
    )
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"])

    op.create_table(
        "audit_events",
        sa.Column("chain_kind", sa.Text(), nullable=False),
        sa.Column("chain_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_label", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=True),
        sa.Column("subject_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("ip", pg.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("data", pg.JSONB(), server_default=EMPTY_JSON, nullable=False),
        sa.Column("hash", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint(
            "chain_kind IN ('system', 'workspace', 'envelope')", name="chain_kind_valid"
        ),
        sa.CheckConstraint("seq >= 1", name="seq_positive"),
        sa.CheckConstraint(
            "actor_type IN ('user', 'recipient', 'system')", name="actor_type_valid"
        ),
        sa.CheckConstraint("octet_length(hash) = 32", name="hash_sha256"),
        sa.PrimaryKeyConstraint("chain_id", "seq", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_workspace_time",
        "audit_events",
        ["workspace_id", sa.text("occurred_at DESC")],
    )

    # Append-only: reject UPDATE, DELETE and TRUNCATE (backbone LLD §4.5).
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    op.drop_table("audit_events")
    op.drop_table("idempotency_keys")
    op.drop_table("jobs")
