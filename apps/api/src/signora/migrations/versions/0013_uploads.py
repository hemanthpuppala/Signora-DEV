"""Uploads: received files waiting to become a document or a version (Phase 4 LLD topic 2).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("department_id", UUID, nullable=False),
        sa.Column("uploaded_by", UUID, nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('pdf', 'docx')", name=op.f("ck_uploads_kind_known")),
        sa.CheckConstraint(
            "char_length(filename) BETWEEN 1 AND 255", name=op.f("ck_uploads_filename_length")
        ),
        sa.CheckConstraint("bytes > 0", name=op.f("ck_uploads_bytes_positive")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_uploads_sha256_hex")),
        sa.ForeignKeyConstraint(
            ["department_id", "workspace_id"],
            ["departments.id", "departments.workspace_id"],
            name=op.f("fk_uploads_department_id_workspace_id_departments"),
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_uploads_uploaded_by_workspace_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
        sa.UniqueConstraint("id", "workspace_id", name=op.f("uq_uploads_id_workspace_id")),
    )
    op.create_index("ix_uploads_expires_at", "uploads", ["expires_at"])


def downgrade() -> None:
    op.drop_table("uploads")
