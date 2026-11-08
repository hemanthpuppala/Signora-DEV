"""Tables of the documents module (Phase 4 LLD). Must match the migrations."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from signora.kernel.db import metadata

# Bytes received and checked, waiting to become a document or a version (topic 2, ADR-DOC1).
uploads = Table(
    "uploads",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("department_id", UUID(as_uuid=True), nullable=False),
    Column("uploaded_by", UUID(as_uuid=True), nullable=False),
    Column("filename", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("bytes", BigInteger, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
    CheckConstraint("kind IN ('pdf', 'docx')", name="kind_known"),
    CheckConstraint("char_length(filename) BETWEEN 1 AND 255", name="filename_length"),
    CheckConstraint("bytes > 0", name="bytes_positive"),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
    UniqueConstraint("id", "workspace_id"),
    ForeignKeyConstraint(
        ["department_id", "workspace_id"], ["departments.id", "departments.workspace_id"]
    ),
    ForeignKeyConstraint(["uploaded_by", "workspace_id"], ["users.id", "users.workspace_id"]),
    Index("ix_uploads_expires_at", "expires_at"),
)

# One agreement inside one department (topic 1).
documents = Table(
    "documents",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("department_id", UUID(as_uuid=True), nullable=False),
    Column("name", Text, nullable=False),
    Column("name_source", Text, nullable=False, server_default=text("'upload'")),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("description_source", Text, nullable=False, server_default=text("'none'")),
    Column("require_email_code", Boolean, nullable=False, server_default=text("true")),
    Column("current_version_id", UUID(as_uuid=True)),
    Column("created_by", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("archived_at", DateTime(timezone=True)),
    Column("archived_by", UUID(as_uuid=True), ForeignKey("users.id")),
    CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_length"),
    CheckConstraint("char_length(description) <= 500", name="description_length"),
    CheckConstraint("name_source IN ('upload', 'ai', 'person')", name="name_source_known"),
    CheckConstraint(
        "description_source IN ('none', 'ai', 'person')", name="description_source_known"
    ),
    CheckConstraint("(archived_at IS NULL) = (archived_by IS NULL)", name="archived_together"),
    UniqueConstraint("id", "workspace_id"),
    ForeignKeyConstraint(
        ["department_id", "workspace_id"], ["departments.id", "departments.workspace_id"]
    ),
    ForeignKeyConstraint(["created_by", "workspace_id"], ["users.id", "users.workspace_id"]),
    # The current version is one of this document's versions (topic 4).
    ForeignKeyConstraint(
        ["current_version_id", "id"],
        ["document_versions.id", "document_versions.document_id"],
        use_alter=True,
    ),
    Index(
        "uq_documents_active_name",
        "department_id",
        text("lower(name)"),
        unique=True,
        postgresql_where=text("archived_at IS NULL"),
    ),
)

# Each upload of a document: immutable once processed (topic 4).
document_versions = Table(
    "document_versions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("document_id", UUID(as_uuid=True), nullable=False),
    Column("version_no", Integer, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'processing'")),
    Column("failure_code", Text),
    Column("failure_temporary", Boolean, nullable=False, server_default=text("false")),
    Column("source_sha256", Text, nullable=False),
    Column("source_kind", Text, nullable=False),
    Column("source_filename", Text, nullable=False),
    Column("source_bytes", BigInteger, nullable=False),
    Column("unlocked_sha256", Text),  # the source opened with its password (§2.6)
    Column("pdf_sha256", Text),
    Column("pdf_bytes", BigInteger),
    Column("page_count", Integer),
    Column("pages", JSONB),
    Column(
        "pages_without_text",
        ARRAY(Integer),
        nullable=False,
        server_default=text("'{}'::integer[]"),
    ),
    Column("ai_instructions", Text, nullable=False, server_default=text("''")),
    Column("ai_description", Text),
    Column("uploaded_by", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("processed_at", DateTime(timezone=True)),
    CheckConstraint("version_no >= 1", name="version_positive"),
    CheckConstraint(
        "status IN ('processing', 'needs_password', 'needs_ocr', 'failed', 'processed')",
        name="status_known",
    ),
    CheckConstraint("(status = 'failed') = (failure_code IS NOT NULL)", name="failure_when_failed"),
    CheckConstraint("source_kind IN ('pdf', 'docx')", name="source_kind_known"),
    CheckConstraint("char_length(ai_instructions) <= 1000", name="ai_instructions_length"),
    CheckConstraint(
        "status <> 'processed' OR (pdf_sha256 IS NOT NULL AND page_count IS NOT NULL)",
        name="processed_has_pdf",
    ),
    UniqueConstraint("document_id", "version_no"),
    UniqueConstraint("id", "workspace_id"),
    UniqueConstraint("id", "document_id"),
    ForeignKeyConstraint(
        ["document_id", "workspace_id"], ["documents.id", "documents.workspace_id"]
    ),
    ForeignKeyConstraint(["uploaded_by", "workspace_id"], ["users.id", "users.workspace_id"]),
    Index("ix_document_versions_source", "workspace_id", "source_sha256"),
)
