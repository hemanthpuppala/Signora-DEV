"""A bulk send's batch and its rows (Bulk send LLD §6).

A batch is one uploaded spreadsheet sent: each row becomes its own envelope. The batch's tables
stand beside ``envelopes`` and do not change it: a row points at the envelope it became.

Numbered after Phase 8's 0025, written on a parallel branch from the same 0024; merged after it,
so it follows 0025.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "envelope_batches",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("department_id", UUID, nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "char_length(file_name) BETWEEN 1 AND 255",
            name=op.f("ck_envelope_batches_file_name_length"),
        ),
        sa.CheckConstraint(
            "total BETWEEN 1 AND 1000", name=op.f("ck_envelope_batches_total_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_envelope_batches")),
        sa.UniqueConstraint("id", "workspace_id", name=op.f("uq_envelope_batches_id_workspace_id")),
        sa.ForeignKeyConstraint(
            ["department_id", "workspace_id"],
            ["departments.id", "departments.workspace_id"],
            name=op.f("fk_envelope_batches_department_id_workspace_id_departments"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            name=op.f("fk_envelope_batches_document_id_workspace_id_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "document_id"],
            ["document_versions.id", "document_versions.document_id"],
            name=op.f("fk_envelope_batches_version_id_document_id_document_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_envelope_batches_created_by_workspace_id_users"),
        ),
    )
    op.create_index(
        "ix_envelope_batches_workspace_id_department_id_created_at",
        "envelope_batches",
        ["workspace_id", "department_id", "created_at"],
    )

    op.create_table(
        "envelope_batch_rows",
        sa.Column("batch_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("request", pg.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("envelope_id", UUID, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name=op.f("ck_envelope_batch_rows_status_known"),
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (request IS NOT NULL)",
            name=op.f("ck_envelope_batch_rows_request_while_pending"),
        ),
        sa.CheckConstraint(
            "(status = 'sent') = (envelope_id IS NOT NULL)",
            name=op.f("ck_envelope_batch_rows_sent_has_envelope"),
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error IS NOT NULL)",
            name=op.f("ck_envelope_batch_rows_failed_has_error"),
        ),
        sa.PrimaryKeyConstraint("batch_id", "row_no", name=op.f("pk_envelope_batch_rows")),
        sa.ForeignKeyConstraint(
            ["batch_id", "workspace_id"],
            ["envelope_batches.id", "envelope_batches.workspace_id"],
            name=op.f("fk_envelope_batch_rows_batch_id_workspace_id_envelope_batches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["envelope_id", "workspace_id"],
            ["envelopes.id", "envelopes.workspace_id"],
            name=op.f("fk_envelope_batch_rows_envelope_id_workspace_id_envelopes"),
        ),
    )


def downgrade() -> None:
    op.drop_table("envelope_batch_rows")
    op.drop_index(
        "ix_envelope_batches_workspace_id_department_id_created_at",
        table_name="envelope_batches",
    )
    op.drop_table("envelope_batches")
