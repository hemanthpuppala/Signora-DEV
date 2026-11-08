"""Documents and their versions (Phase 4 LLD topics 1 and 4).

``documents.current_version_id`` references ``(id, document_id)`` of a version, so the current
version always belongs to the same document (and so the same company and department).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("department_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_source", sa.Text(), server_default=sa.text("'upload'"), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "description_source", sa.Text(), server_default=sa.text("'none'"), nullable=False
        ),
        sa.Column(
            "require_email_code", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("current_version_id", UUID, nullable=True),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", UUID, nullable=True),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120", name=op.f("ck_documents_name_length")
        ),
        sa.CheckConstraint(
            "char_length(description) <= 500", name=op.f("ck_documents_description_length")
        ),
        sa.CheckConstraint(
            "name_source IN ('upload', 'ai', 'person')", name=op.f("ck_documents_name_source_known")
        ),
        sa.CheckConstraint(
            "description_source IN ('none', 'ai', 'person')",
            name=op.f("ck_documents_description_source_known"),
        ),
        sa.CheckConstraint(
            "(archived_at IS NULL) = (archived_by IS NULL)",
            name=op.f("ck_documents_archived_together"),
        ),
        sa.ForeignKeyConstraint(
            ["department_id", "workspace_id"],
            ["departments.id", "departments.workspace_id"],
            name=op.f("fk_documents_department_id_workspace_id_departments"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_documents_created_by_workspace_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["archived_by"], ["users.id"], name=op.f("fk_documents_archived_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("id", "workspace_id", name=op.f("uq_documents_id_workspace_id")),
    )
    op.create_index(
        "uq_documents_active_name",
        "documents",
        ["department_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'processing'"), nullable=False),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column(
            "failure_temporary", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("source_bytes", sa.BigInteger(), nullable=False),
        sa.Column("unlocked_sha256", sa.Text(), nullable=True),
        sa.Column("pdf_sha256", sa.Text(), nullable=True),
        sa.Column("pdf_bytes", sa.BigInteger(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("pages", pg.JSONB(), nullable=True),
        sa.Column(
            "pages_without_text",
            pg.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column("ai_instructions", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("ai_description", sa.Text(), nullable=True),
        sa.Column("uploaded_by", UUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version_no >= 1", name=op.f("ck_document_versions_version_positive")),
        sa.CheckConstraint(
            "status IN ('processing', 'needs_password', 'needs_ocr', 'failed', 'processed')",
            name=op.f("ck_document_versions_status_known"),
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL)",
            name=op.f("ck_document_versions_failure_when_failed"),
        ),
        sa.CheckConstraint(
            "source_kind IN ('pdf', 'docx')", name=op.f("ck_document_versions_source_kind_known")
        ),
        sa.CheckConstraint(
            "char_length(ai_instructions) <= 1000",
            name=op.f("ck_document_versions_ai_instructions_length"),
        ),
        sa.CheckConstraint(
            "status <> 'processed' OR (pdf_sha256 IS NOT NULL AND page_count IS NOT NULL)",
            name=op.f("ck_document_versions_processed_has_pdf"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            name=op.f("fk_document_versions_document_id_workspace_id_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_document_versions_uploaded_by_workspace_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "document_id", "version_no", name=op.f("uq_document_versions_document_id_version_no")
        ),
        sa.UniqueConstraint(
            "id", "workspace_id", name=op.f("uq_document_versions_id_workspace_id")
        ),
        sa.UniqueConstraint("id", "document_id", name=op.f("uq_document_versions_id_document_id")),
    )
    op.create_index(
        "ix_document_versions_source", "document_versions", ["workspace_id", "source_sha256"]
    )
    op.create_foreign_key(
        op.f("fk_documents_current_version_id_id_document_versions"),
        "documents",
        "document_versions",
        ["current_version_id", "id"],
        ["id", "document_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_documents_current_version_id_id_document_versions"),
        "documents",
        type_="foreignkey",
    )
    op.drop_table("document_versions")
    op.drop_table("documents")
