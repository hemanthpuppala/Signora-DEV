"""Tables of a bulk send (Bulk send LLD §6). Must match migration 0026."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from signora.kernel.db import metadata

# One upload sent: a template's version, who sent it, how many rows.
envelope_batches = Table(
    "envelope_batches",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("department_id", UUID(as_uuid=True), nullable=False),
    Column("document_id", UUID(as_uuid=True), nullable=False),
    Column("version_id", UUID(as_uuid=True), nullable=False),
    Column("created_by", UUID(as_uuid=True), nullable=False),  # the sender; the job acts as them
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),  # null while rows are still to be sent
    Column("file_name", Text, nullable=False),
    Column("total", Integer, nullable=False),
    CheckConstraint("char_length(file_name) BETWEEN 1 AND 255", name="file_name_length"),
    CheckConstraint("total BETWEEN 1 AND 1000", name="total_range"),
    UniqueConstraint("id", "workspace_id"),
    ForeignKeyConstraint(
        ["department_id", "workspace_id"], ["departments.id", "departments.workspace_id"]
    ),
    ForeignKeyConstraint(
        ["document_id", "workspace_id"], ["documents.id", "documents.workspace_id"]
    ),
    ForeignKeyConstraint(
        ["version_id", "document_id"], ["document_versions.id", "document_versions.document_id"]
    ),
    ForeignKeyConstraint(["created_by", "workspace_id"], ["users.id", "users.workspace_id"]),
    Index(None, "workspace_id", "department_id", "created_at"),  # a department's recent batches
)

# One row of the upload: an envelope to send, then the envelope it became or why it did not.
envelope_batch_rows = Table(
    "envelope_batch_rows",
    metadata,
    Column("batch_id", UUID(as_uuid=True), nullable=False),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("row_no", Integer, nullable=False),  # the file's row number, as the sender sees it
    Column("label", Text, nullable=False),  # who it is for, to name it once its data is gone
    # The row as a send request; erased once the row is settled (the envelope holds it from there).
    Column("request", JSONB),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("envelope_id", UUID(as_uuid=True)),
    Column("error", Text),
    PrimaryKeyConstraint("batch_id", "row_no"),
    CheckConstraint("status IN ('pending', 'sent', 'failed')", name="status_known"),
    CheckConstraint("(status = 'pending') = (request IS NOT NULL)", name="request_while_pending"),
    CheckConstraint("(status = 'sent') = (envelope_id IS NOT NULL)", name="sent_has_envelope"),
    CheckConstraint("(status = 'failed') = (error IS NOT NULL)", name="failed_has_error"),
    ForeignKeyConstraint(
        ["batch_id", "workspace_id"],
        ["envelope_batches.id", "envelope_batches.workspace_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["envelope_id", "workspace_id"], ["envelopes.id", "envelopes.workspace_id"]
    ),
)
