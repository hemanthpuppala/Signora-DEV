"""Table definition for ``audit_events`` (backbone LLD §4.6). Must match migration 0001.

The append-only triggers are created by the migration; they are not part of the table metadata.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID

from signora.kernel.db import metadata

audit_events = Table(
    "audit_events",
    metadata,
    Column("chain_kind", Text, nullable=False),
    Column("chain_id", UUID(as_uuid=True), nullable=False),
    Column("seq", BigInteger, nullable=False),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("actor_type", Text, nullable=False),
    Column("actor_id", UUID(as_uuid=True)),
    Column("actor_label", Text),
    Column("action", Text, nullable=False),
    Column("subject_type", Text),
    Column("subject_id", UUID(as_uuid=True)),
    Column("request_id", Text),
    Column("ip", INET),
    Column("user_agent", Text),
    Column("data", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("hash", LargeBinary, nullable=False),
    CheckConstraint("chain_kind IN ('system', 'workspace', 'envelope')", name="chain_kind_valid"),
    CheckConstraint("seq >= 1", name="seq_positive"),
    CheckConstraint("actor_type IN ('user', 'recipient', 'system')", name="actor_type_valid"),
    CheckConstraint("octet_length(hash) = 32", name="hash_sha256"),
    PrimaryKeyConstraint("chain_id", "seq"),
    Index("ix_audit_events_workspace_time", "workspace_id", text("occurred_at DESC")),
    # One subject's history, e.g. an envelope's timeline (Phase 7 §6).
    Index(
        "ix_audit_events_subject_type_subject_id_occurred_at",
        "subject_type",
        "subject_id",
        "occurred_at",
    ),
)
