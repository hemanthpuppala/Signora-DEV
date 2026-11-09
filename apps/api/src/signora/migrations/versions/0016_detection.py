"""Field detection (Phase 5 LLD topics 1 and 5).

A version's status ``processed`` is replaced by ``detecting`` (finding its fields) and ``ready``.
Every version that was processed becomes ``detecting`` and gets its detection queued, so existing
documents go through it once (owner decision). New tables: one detection run per version, and the
version's roles, fields and field placements.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
# The job kind below is the detection module's subscriber for DocumentVersionProcessed (kernel
# events name one job kind per subscriber: event:<Event>:<subscriber>). Values are written into the
# SQL as literals: a migration is a snapshot and must not change when code does.


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_document_versions_status_known"), "document_versions", type_="check"
    )
    op.drop_constraint(
        op.f("ck_document_versions_processed_has_pdf"), "document_versions", type_="check"
    )
    op.execute("UPDATE document_versions SET status = 'detecting' WHERE status = 'processed'")
    op.create_check_constraint(
        op.f("ck_document_versions_status_known"),
        "document_versions",
        "status IN ('processing', 'needs_password', 'needs_ocr', 'failed', 'detecting', 'ready')",
    )
    op.create_check_constraint(
        op.f("ck_document_versions_processed_has_pdf"),
        "document_versions",
        "status NOT IN ('detecting', 'ready') "
        "OR (pdf_sha256 IS NOT NULL AND page_count IS NOT NULL)",
    )
    # How many fields a ready version has, for the lists (§6.5); set when detection finishes.
    op.add_column("document_versions", sa.Column("field_count", sa.Integer(), nullable=True))
    # Queue detection for every version that was processed, as the event would have.
    op.execute(
        """
        INSERT INTO jobs (kind, payload, dedupe_key)
        SELECT 'event:DocumentVersionProcessed:detection',
               jsonb_build_object(
                   'event_id', e.event_id,
                   'occurred_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
                   'workspace_id', v.workspace_id,
                   'document_id', v.document_id,
                   'version_id', v.id),
               'event:' || e.event_id || ':' || 'detection'
        FROM document_versions v
        CROSS JOIN LATERAL (SELECT gen_random_uuid() AS event_id) e
        WHERE v.status = 'detecting'
        """
    )

    op.create_table(
        "detection_runs",
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("stage", sa.Text(), server_default=sa.text("'read'"), nullable=False),
        sa.Column("fields_from", sa.Text(), nullable=True),
        sa.Column("parsed", pg.JSONB(), nullable=True),
        sa.Column("layout", sa.Text(), nullable=True),
        sa.Column("calls", pg.JSONB(), nullable=True),
        sa.Column("answer", pg.JSONB(), nullable=True),
        sa.Column("result", pg.JSONB(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("requested_by", UUID, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "stage IN ('read', 'ai', 'derive', 'store', 'done')",
            name=op.f("ck_detection_runs_stage_known"),
        ),
        sa.CheckConstraint(
            "fields_from IN ('form_fields', 'blanks', 'none')",
            name=op.f("ck_detection_runs_fields_from_known"),
        ),
        sa.CheckConstraint(
            "(stage = 'done') = (finished_at IS NOT NULL)",
            name=op.f("ck_detection_runs_done_when_finished"),
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "workspace_id"],
            ["document_versions.id", "document_versions.workspace_id"],
            name=op.f("fk_detection_runs_version_id_workspace_id_document_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_detection_runs_requested_by_workspace_id_users"),
        ),
        sa.PrimaryKeyConstraint("version_id", name=op.f("pk_detection_runs")),
    )

    op.create_table(
        "version_roles",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('signer', 'countersigner')", name=op.f("ck_version_roles_kind_known")
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "workspace_id"],
            ["document_versions.id", "document_versions.workspace_id"],
            name=op.f("fk_version_roles_version_id_workspace_id_document_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_version_roles")),
        sa.UniqueConstraint("version_id", "slug", name=op.f("uq_version_roles_version_id_slug")),
        sa.UniqueConstraint("id", "version_id", name=op.f("uq_version_roles_id_version_id")),
    )

    op.create_table(
        "version_fields",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("holds", sa.Text(), nullable=False),
        sa.Column("filled_by", sa.Text(), nullable=False),
        sa.Column("role_id", UUID, nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("depends_on_field_id", UUID, nullable=True),
        sa.Column("depends_on_option", sa.Text(), nullable=True),
        sa.Column("needs_review", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "filled_by IN ('role', 'sender', 'none')",
            name=op.f("ck_version_fields_filled_by_known"),
        ),
        sa.CheckConstraint(
            "origin IN ('detected', 'added')", name=op.f("ck_version_fields_origin_known")
        ),
        sa.CheckConstraint(
            "(filled_by = 'role') = (role_id IS NOT NULL)",
            name=op.f("ck_version_fields_role_when_filled_by_role"),
        ),
        sa.CheckConstraint(
            "(depends_on_field_id IS NULL) = (depends_on_option IS NULL)",
            name=op.f("ck_version_fields_dependency_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "workspace_id"],
            ["document_versions.id", "document_versions.workspace_id"],
            name=op.f("fk_version_fields_version_id_workspace_id_document_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["role_id", "version_id"],
            ["version_roles.id", "version_roles.version_id"],
            name=op.f("fk_version_fields_role_id_version_id_version_roles"),
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_field_id", "version_id"],
            ["version_fields.id", "version_fields.version_id"],
            name=op.f("fk_version_fields_depends_on_field_id_version_id_version_fields"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_version_fields")),
        sa.UniqueConstraint("version_id", "key", name=op.f("uq_version_fields_version_id_key")),
        sa.UniqueConstraint("id", "version_id", name=op.f("uq_version_fields_id_version_id")),
    )

    op.create_table(
        "field_placements",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("x0", sa.Float(), nullable=False),
        sa.Column("y0", sa.Float(), nullable=False),
        sa.Column("x1", sa.Float(), nullable=False),
        sa.Column("y1", sa.Float(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("pdf_field", sa.Text(), nullable=True),
        sa.Column("option_value", sa.Text(), nullable=True),
        sa.Column("option_text", sa.Text(), nullable=True),
        sa.CheckConstraint("page >= 1", name=op.f("ck_field_placements_page_positive")),
        sa.CheckConstraint(
            "kind IN ('text', 'signature', 'checkbox', 'radio', 'combobox', 'listbox', 'blank')",
            name=op.f("ck_field_placements_kind_known"),
        ),
        sa.ForeignKeyConstraint(
            ["field_id", "version_id"],
            ["version_fields.id", "version_fields.version_id"],
            name=op.f("fk_field_placements_field_id_version_id_version_fields"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_placements")),
    )
    op.create_index("ix_version_fields_version_id", "version_fields", ["version_id"])
    op.create_index("ix_field_placements_version_id", "field_placements", ["version_id"])
    op.create_index("ix_field_placements_field_id", "field_placements", ["field_id"])


def downgrade() -> None:
    op.drop_index("ix_field_placements_field_id", table_name="field_placements")
    op.drop_index("ix_field_placements_version_id", table_name="field_placements")
    op.drop_index("ix_version_fields_version_id", table_name="version_fields")
    op.drop_table("field_placements")
    op.drop_table("version_fields")
    op.drop_table("version_roles")
    op.drop_table("detection_runs")
    op.drop_column("document_versions", "field_count")
    op.execute(
        "DELETE FROM jobs WHERE kind = 'event:DocumentVersionProcessed:detection' "
        "AND status IN ('queued', 'running')"
    )
    op.drop_constraint(
        op.f("ck_document_versions_status_known"), "document_versions", type_="check"
    )
    op.drop_constraint(
        op.f("ck_document_versions_processed_has_pdf"), "document_versions", type_="check"
    )
    # A version that failed detection had been processed: it goes back to processed.
    op.execute(
        "UPDATE document_versions SET status = 'processed', failure_code = NULL, "
        "failure_temporary = false WHERE status IN ('detecting', 'ready') OR (status = 'failed' "
        "AND failure_code IN ('ai_not_configured', 'ai_unavailable', 'detection_failed'))"
    )
    op.create_check_constraint(
        op.f("ck_document_versions_status_known"),
        "document_versions",
        "status IN ('processing', 'needs_password', 'needs_ocr', 'failed', 'processed')",
    )
    op.create_check_constraint(
        op.f("ck_document_versions_processed_has_pdf"),
        "document_versions",
        "status <> 'processed' OR (pdf_sha256 IS NOT NULL AND page_count IS NOT NULL)",
    )
