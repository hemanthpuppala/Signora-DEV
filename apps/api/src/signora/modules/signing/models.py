"""Tables of the signing module (Phase 8 LLD §15). Must match migration 0025.

A recipient's rows carry their company with them (composite keys to ``envelope_recipients``), as
the envelope's own tables do. The foreign keys to recipients are named by hand: the naming
convention's names would pass Postgres's 63 characters.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID

from signora.kernel.db import metadata


def _recipient(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["recipient_id", "workspace_id"],
        ["envelope_recipients.id", "envelope_recipients.workspace_id"],
        name=f"fk_{table}_recipient_envelope_recipients",
    )


def _signature_columns() -> list[Column[Any]]:
    """A typed signature is its text in a font; a drawn one is its strokes (§5.5)."""
    return [
        Column("kind", Text, nullable=False),
        Column("method", Text, nullable=False),
        Column("text", Text),
        Column("font", Text),
        Column("strokes", JSONB),
        Column("sha256", LargeBinary, nullable=False),
    ]


def _signature_checks() -> list[CheckConstraint]:
    return [
        CheckConstraint("kind IN ('signature', 'initials')", name="kind_known"),
        CheckConstraint(
            "method = 'typed' AND text IS NOT NULL AND font IS NOT NULL AND strokes IS NULL "
            "OR method = 'drawn' AND strokes IS NOT NULL AND text IS NULL AND font IS NULL",
            name="method_shape",
        ),
        CheckConstraint("text IS NULL OR char_length(text) BETWEEN 1 AND 100", name="text_length"),
        CheckConstraint("octet_length(sha256) = 32", name="sha256_length"),
    ]


# A browser's signing session (§1.3): only the cookie's hash is kept.
signing_sessions = Table(
    "signing_sessions",
    metadata,
    Column("id_hash", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("octet_length(id_hash) = 32", name="id_hash_sha256"),
    PrimaryKeyConstraint("id_hash"),
    Index(None, "expires_at"),
)

# Each person opened in a browser session (§1.4). ``link_version`` is the one their link carried.
signing_grants = Table(
    "signing_grants",
    metadata,
    Column("session_hash", LargeBinary, nullable=False),
    Column("recipient_id", UUID(as_uuid=True), nullable=False),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("link_version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("verified_at", DateTime(timezone=True)),
    PrimaryKeyConstraint("session_hash", "recipient_id"),
    ForeignKeyConstraint(["session_hash"], ["signing_sessions.id_hash"], ondelete="CASCADE"),
    _recipient("signing_grants"),
)

# At most one live email code per person (§2.2): only its keyed hash.
signing_codes = Table(
    "signing_codes",
    metadata,
    Column("recipient_id", UUID(as_uuid=True), nullable=False),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("link_version", Integer, nullable=False),
    Column("code_mac", LargeBinary, nullable=False),
    Column("sent_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("wrong_tries", SmallInteger, nullable=False, server_default=text("0")),
    Column("used_at", DateTime(timezone=True)),
    Column("window_start", DateTime(timezone=True), nullable=False),
    Column("sent_in_window", SmallInteger, nullable=False, server_default=text("1")),
    CheckConstraint("octet_length(code_mac) = 32", name="code_mac_length"),
    CheckConstraint("wrong_tries BETWEEN 0 AND 20", name="wrong_tries_range"),
    CheckConstraint("sent_in_window BETWEEN 1 AND 5", name="sent_in_window_range"),
    PrimaryKeyConstraint("recipient_id"),
    _recipient("signing_codes"),
)

# Consent to electronic records (§3.2): a fact once given (a trigger refuses changes).
signing_consents = Table(
    "signing_consents",
    metadata,
    Column("recipient_id", UUID(as_uuid=True), nullable=False),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("disclosure_version", Text, nullable=False),
    Column("consented_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("ip", INET),  # unknown when no valid address reached us
    Column("user_agent", Text),
    CheckConstraint(
        "char_length(disclosure_version) BETWEEN 1 AND 40", name="disclosure_version_length"
    ),
    CheckConstraint(
        "user_agent IS NULL OR char_length(user_agent) <= 512", name="user_agent_length"
    ),
    PrimaryKeyConstraint("recipient_id"),
    _recipient("signing_consents"),
)

# A person's values before they submit (§4.7); nobody else reads them.
signing_drafts = Table(
    "signing_drafts",
    metadata,
    Column("recipient_id", UUID(as_uuid=True), nullable=False),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("version_id", UUID(as_uuid=True), nullable=False),
    Column("field_id", UUID(as_uuid=True), nullable=False),
    Column("value", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("char_length(value) <= 2000", name="value_length"),
    PrimaryKeyConstraint("recipient_id", "field_id"),
    ForeignKeyConstraint(
        ["recipient_id", "workspace_id", "version_id"],
        [
            "envelope_recipients.id",
            "envelope_recipients.workspace_id",
            "envelope_recipients.version_id",
        ],
        name="fk_signing_drafts_recipient_envelope_recipients",
    ),
    ForeignKeyConstraint(
        ["field_id", "version_id"], ["version_fields.id", "version_fields.version_id"]
    ),
    # Every review save deletes fields: their foreign-key check is an index lookup, not a scan.
    Index(None, "field_id"),
)

# What a person adopted for one envelope (§5.5): evidence, frozen once they have signed (a trigger).
signing_signatures = Table(
    "signing_signatures",
    metadata,
    Column("recipient_id", UUID(as_uuid=True), nullable=False),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    *_signature_columns(),
    Column("adopted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    *_signature_checks(),
    PrimaryKeyConstraint("recipient_id", "kind"),
    _recipient("signing_signatures"),
)

# A Signora user's signature, saved on their first countersign (§5.4).
saved_signatures = Table(
    "saved_signatures",
    metadata,
    Column("user_id", UUID(as_uuid=True), nullable=False),
    *_signature_columns(),
    Column("saved_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    *_signature_checks(),
    PrimaryKeyConstraint("user_id", "kind"),
    ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
)
