"""Tables of the envelopes module (Phase 7 LLD §9). Must match migrations 0019 to 0034."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from signora.kernel.db import metadata

# One send of one approved version (§1): pinned, with its own settings (§4).
envelopes = Table(
    "envelopes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("department_id", UUID(as_uuid=True), nullable=False),
    Column("document_id", UUID(as_uuid=True), nullable=False),
    Column("version_id", UUID(as_uuid=True), nullable=False),
    Column("title", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'sent'")),
    Column("require_email_code", Boolean, nullable=False),
    # The font its values are drawn in (Phase 7b): the preview's and the signed PDF's.
    Column("font", Text, nullable=False, server_default=text("'liberation-sans'")),
    # The sender's time zone (IANA), for the dates in its emails (Phase 7b).
    Column("time_zone", Text, nullable=False, server_default=text("'UTC'")),
    Column("reminder_interval_hours", Integer, nullable=False),
    Column("max_reminders", Integer, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("notify_emails", ARRAY(Text), nullable=False),
    Column("sent_by", UUID(as_uuid=True), nullable=False),
    Column("sent_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("completed_at", DateTime(timezone=True)),
    Column("cancelled_at", DateTime(timezone=True)),
    Column("cancelled_by", UUID(as_uuid=True)),
    Column("signed_blob", Text),
    Column("signed_sha256", LargeBinary),
    Column("certificate_blob", Text),
    Column("certificate_sha256", LargeBinary),
    CheckConstraint(
        "status IN ('sent', 'opened', 'viewed', 'signed', 'completed', 'declined', 'expired', "
        "'cancelled')",
        name="status_known",
    ),
    CheckConstraint("char_length(title) BETWEEN 1 AND 120", name="title_length"),
    CheckConstraint(
        "reminder_interval_hours BETWEEN 1 AND 720", name="reminder_interval_hours_range"
    ),
    CheckConstraint("max_reminders BETWEEN 0 AND 20", name="max_reminders_range"),
    CheckConstraint("cardinality(notify_emails) <= 5", name="notify_emails_count"),
    CheckConstraint(
        "(status = 'cancelled') = (cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL)",
        name="cancelled_is_recorded",
    ),
    CheckConstraint(
        "(status = 'completed') = (completed_at IS NOT NULL)", name="completed_is_recorded"
    ),
    # The completed document and its certificate (Phase 8 §12): set together, once (a trigger).
    CheckConstraint(
        "(status = 'completed') = (signed_blob IS NOT NULL AND signed_sha256 IS NOT NULL "
        "AND certificate_blob IS NOT NULL AND certificate_sha256 IS NOT NULL)",
        name="completed_has_files",
    ),
    CheckConstraint(
        "(signed_sha256 IS NULL OR octet_length(signed_sha256) = 32) AND "
        "(certificate_sha256 IS NULL OR octet_length(certificate_sha256) = 32)",
        name="file_hashes_length",
    ),
    UniqueConstraint("id", "workspace_id"),
    UniqueConstraint("id", "version_id"),
    ForeignKeyConstraint(
        ["department_id", "workspace_id"], ["departments.id", "departments.workspace_id"]
    ),
    ForeignKeyConstraint(
        ["document_id", "workspace_id"], ["documents.id", "documents.workspace_id"]
    ),
    ForeignKeyConstraint(
        ["version_id", "document_id"], ["document_versions.id", "document_versions.document_id"]
    ),
    ForeignKeyConstraint(["sent_by", "workspace_id"], ["users.id", "users.workspace_id"]),
    ForeignKeyConstraint(["cancelled_by", "workspace_id"], ["users.id", "users.workspace_id"]),
    Index(None, "workspace_id", "department_id", "status", "sent_at"),  # a department's, by state
    Index(None, "workspace_id", "department_id", "sent_at", "id"),  # a department's, newest first
    Index(None, "document_id"),
    Index(
        "ix_envelopes_title_trgm",
        "title",
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    ),  # search (ADR S-1)
)

# Who an envelope goes to (§2, §3): the version's signers and countersigners, and people who
# receive a copy. ``link_version`` revokes every earlier signing link when it moves on (ADR-E1).
envelope_recipients = Table(
    "envelope_recipients",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("envelope_id", UUID(as_uuid=True), nullable=False),
    Column("version_id", UUID(as_uuid=True), nullable=False),
    Column("party_id", UUID(as_uuid=True)),
    Column("kind", Text, nullable=False),
    Column("stage", Integer, nullable=False),
    Column("position", Integer, nullable=False),
    Column("name", Text, nullable=False),
    Column("email", Text, nullable=False),
    Column("user_id", UUID(as_uuid=True)),
    Column("status", Text, nullable=False),
    Column("link_version", Integer, nullable=False, server_default=text("1")),
    Column("revoked_at", DateTime(timezone=True)),
    Column("reminders_sent", Integer, nullable=False, server_default=text("0")),
    Column("next_reminder_at", DateTime(timezone=True)),
    Column("last_email_id", UUID(as_uuid=True)),
    Column("sent_at", DateTime(timezone=True)),
    Column("opened_at", DateTime(timezone=True)),
    Column("viewed_at", DateTime(timezone=True)),
    Column("signed_at", DateTime(timezone=True)),
    Column("declined_at", DateTime(timezone=True)),
    Column("decline_reason", Text),
    CheckConstraint("kind IN ('signer', 'countersigner', 'copy')", name="kind_known"),
    CheckConstraint(
        "kind = 'signer' AND stage = 1 OR kind = 'countersigner' AND stage = 2 "
        "OR kind = 'copy' AND stage = 3",
        name="stage_of_kind",
    ),
    CheckConstraint("(kind = 'copy') = (party_id IS NULL)", name="party_unless_copy"),
    CheckConstraint(
        "(kind = 'countersigner') = (user_id IS NOT NULL)", name="user_for_countersigner"
    ),
    CheckConstraint(
        "status IN ('waiting', 'sent', 'opened', 'viewed', 'signed', 'declined')",
        name="status_known",
    ),
    CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_length"),
    CheckConstraint("link_version >= 1", name="link_positive"),
    CheckConstraint("position >= 1", name="position_positive"),
    # A decline (Phase 8 §8.3): who, when, why; final.
    CheckConstraint(
        "(status = 'declined') = (declined_at IS NOT NULL AND decline_reason IS NOT NULL)",
        name="declined_is_recorded",
    ),
    CheckConstraint(
        "decline_reason IS NULL OR char_length(btrim(decline_reason)) BETWEEN 1 AND 500",
        name="decline_reason_length",
    ),
    UniqueConstraint("id", "workspace_id"),
    UniqueConstraint("id", "workspace_id", "version_id"),
    UniqueConstraint("envelope_id", "party_id"),
    UniqueConstraint("envelope_id", "stage", "position"),
    ForeignKeyConstraint(
        ["envelope_id", "workspace_id"], ["envelopes.id", "envelopes.workspace_id"]
    ),
    ForeignKeyConstraint(["envelope_id", "version_id"], ["envelopes.id", "envelopes.version_id"]),
    ForeignKeyConstraint(
        ["party_id", "version_id"], ["version_roles.id", "version_roles.version_id"]
    ),
    ForeignKeyConstraint(["user_id", "workspace_id"], ["users.id", "users.workspace_id"]),
    ForeignKeyConstraint(["last_email_id"], ["email_messages.id"]),
    Index(None, "envelope_id"),
    # Rows deleted elsewhere: a review save's parties, old mail cleared; each check an index lookup.
    Index(None, "party_id"),
    Index(None, "last_email_id"),
    # A countersigner's inbox (Phase 8 §7.2): their waiting envelopes, one index range.
    Index(None, "user_id", "status", postgresql_where=text("kind = 'countersigner'")),
    # The reminder sweep (reminders LLD §7): due people by one index range of live schedules.
    Index(None, "next_reminder_at", postgresql_where=text("next_reminder_at IS NOT NULL")),
    # Search by a person's name or email (ADR S-1).
    Index(
        "ix_envelope_recipients_name_trgm",
        "name",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    ),
    Index(
        "ix_envelope_recipients_email_trgm",
        "email",
        postgresql_using="gin",
        postgresql_ops={"email": "gin_trgm_ops"},
    ),
)

# Values given before signing (§2): the sender's own (never change, a trigger); a signer's name and
# email prefilled into their fields ("prefill", tied to that recipient: they follow a corrected
# email); from Phase 8, what each signer gives ("recipient").
envelope_values = Table(
    "envelope_values",
    metadata,
    Column("envelope_id", UUID(as_uuid=True), nullable=False),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("version_id", UUID(as_uuid=True), nullable=False),
    Column("field_id", UUID(as_uuid=True), nullable=False),
    Column("value", Text, nullable=False),
    Column("given_by", Text, nullable=False),
    Column("recipient_id", UUID(as_uuid=True)),
    Column("given_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("given_by IN ('sender', 'prefill', 'recipient')", name="given_by_known"),
    CheckConstraint(
        "(given_by = 'sender') = (recipient_id IS NULL)", name="recipient_unless_sender"
    ),
    CheckConstraint("char_length(value) <= 2000", name="value_length"),
    PrimaryKeyConstraint("envelope_id", "field_id"),
    ForeignKeyConstraint(
        ["envelope_id", "workspace_id"], ["envelopes.id", "envelopes.workspace_id"]
    ),
    ForeignKeyConstraint(["envelope_id", "version_id"], ["envelopes.id", "envelopes.version_id"]),
    ForeignKeyConstraint(
        ["field_id", "version_id"], ["version_fields.id", "version_fields.version_id"]
    ),
    ForeignKeyConstraint(["recipient_id"], ["envelope_recipients.id"]),
    # Every review save deletes fields: their foreign-key check is an index lookup, not a scan.
    Index(None, "field_id"),
)
