"""Tables of the notifications module: ``email_messages`` (Phase 2 LLD §1a.4) and its attachments
(Phase 8). Must match migrations 0002, 0019 and 0025.

``workspace_id`` has no foreign key: this leaf module owns no workspace table, and auth emails sent
before a workspace exists carry none (the audit table follows the same rule).
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from signora.kernel.db import metadata

email_messages = Table(
    "email_messages",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True)),
    Column("category", Text, nullable=False),
    Column("to_address", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("text_body", Text),
    Column("html_body", Text),
    Column("status", Text, nullable=False, server_default=text("'queued'")),
    Column("provider", Text),
    Column("provider_message_id", Text),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("last_error", Text),
    Column("dedupe_key", Text, unique=True),
    Column("reply_to", Text),  # the person replies reach (Phase 7: the sender)
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("sent_at", DateTime(timezone=True)),
    Column("failed_at", DateTime(timezone=True)),
    CheckConstraint("status IN ('queued', 'sent', 'failed')", name="status_valid"),
    CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    # A final message keeps no body: it held sign-in links.
    CheckConstraint(
        "status = 'queued' OR (text_body IS NULL AND html_body IS NULL)", name="final_has_no_body"
    ),
    Index("ix_email_messages_status_created_at", "status", "created_at"),
)

# Files an email carries (Phase 8 §15): blob keys, read by the transport when it sends, so an email
# keeps no file bytes of its own.
email_attachments = Table(
    "email_attachments",
    metadata,
    Column(
        "email_id",
        UUID(as_uuid=True),
        ForeignKey("email_messages.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("position", SmallInteger, nullable=False),
    Column("blob_key", Text, nullable=False),
    Column("filename", Text, nullable=False),
    Column("content_type", Text, nullable=False),
    CheckConstraint("position >= 1", name="position_positive"),
    CheckConstraint("char_length(filename) BETWEEN 1 AND 200", name="filename_length"),
    PrimaryKeyConstraint("email_id", "position"),
)
