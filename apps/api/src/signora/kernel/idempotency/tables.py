"""Table definition for ``idempotency_keys`` (backbone LLD §3.5). Must match migration 0001."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from signora.kernel.db import metadata

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("scope", Text, nullable=False),
    Column("key", Text, nullable=False),
    Column("request_hash", LargeBinary, nullable=False),
    Column("response_status", SmallInteger),
    Column("response_body", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("char_length(key) BETWEEN 1 AND 255", name="key_length"),
    CheckConstraint("octet_length(request_hash) = 32", name="request_hash_sha256"),
    PrimaryKeyConstraint("scope", "key"),
    Index("ix_idempotency_keys_created_at", "created_at"),
)
