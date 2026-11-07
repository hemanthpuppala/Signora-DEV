"""Table definition for ``jobs`` (backbone LLD topic 2). Must match migration 0001."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from signora.kernel.db import metadata

jobs = Table(
    "jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("kind", Text, nullable=False),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("meta", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("status", Text, nullable=False, server_default=text("'queued'")),
    Column("dedupe_key", Text),
    Column("run_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("last_error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    CheckConstraint("status IN ('queued', 'running', 'succeeded', 'dead')", name="status_valid"),
    CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    UniqueConstraint("dedupe_key"),
    Index("ix_jobs_due", "run_at", postgresql_where=text("status = 'queued'")),
    Index("ix_jobs_lease", "lease_expires_at", postgresql_where=text("status = 'running'")),
    Index("ix_jobs_finished", "finished_at", postgresql_where=text("status = 'succeeded'")),
)
