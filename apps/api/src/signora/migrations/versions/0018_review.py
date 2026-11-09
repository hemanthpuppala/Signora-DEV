"""Field review and approval (Phase 6 LLD §9).

A version can be approved (frozen, sendable); one made by editing an approved version records its
source. A version's name and description lose their ``ai_`` prefix (an edited version's are not the
AI's). Parties and fields gain the typed text of an Other kind or type. Review keeps each version's
revision, the document's flags detection found, and, once approved, its metrics; a trigger refuses
any change to an approved version's parties, fields or places. No version is approved yet, so
documents have no current version until one is (current means the newest approved version); ready
versions stay in review.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
STATUSES_BEFORE = "('processing', 'needs_password', 'needs_ocr', 'failed', 'detecting', 'ready')"
STATUSES = (
    "('processing', 'needs_password', 'needs_ocr', 'failed', 'detecting', 'ready', 'approved')"
)
FIELD_TABLES = ("version_roles", "version_fields", "field_placements")
# Columns of version_fields that refer to another row (a party, a field), indexed for deletes.
REFERRING = ("role_id", "depends_on_field_id")
# One statement-level trigger per event: (event, transition tables, function).
TRIGGERS = (
    ("INSERT", "NEW TABLE AS touched", "review_forbid_approved_rows"),
    ("DELETE", "OLD TABLE AS touched", "review_forbid_approved_rows"),
    (
        "UPDATE",
        "OLD TABLE AS touched_before NEW TABLE AS touched",
        "review_forbid_approved_updates",
    ),
)


def upgrade() -> None:
    # Versions: the approved state, who approved, the source of an edited version, plain names.
    op.alter_column("document_versions", "ai_name", new_column_name="name")
    op.alter_column("document_versions", "ai_description", new_column_name="description")
    op.add_column("document_versions", sa.Column("derived_from_version_id", UUID, nullable=True))
    op.add_column("document_versions", sa.Column("approved_by", UUID, nullable=True))
    op.add_column(
        "document_versions", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_document_versions_derived_from_version_id_document_versions"),
        "document_versions",
        "document_versions",
        ["derived_from_version_id", "document_id"],
        ["id", "document_id"],
    )
    op.create_foreign_key(
        op.f("fk_document_versions_approved_by_users"),
        "document_versions",
        "users",
        ["approved_by", "workspace_id"],
        ["id", "workspace_id"],
    )
    for name in ("status_known", "processed_has_pdf"):
        op.drop_constraint(op.f(f"ck_document_versions_{name}"), "document_versions", type_="check")
    op.create_check_constraint(
        op.f("ck_document_versions_status_known"), "document_versions", f"status IN {STATUSES}"
    )
    op.create_check_constraint(
        op.f("ck_document_versions_processed_has_pdf"),
        "document_versions",
        "status NOT IN ('detecting', 'ready', 'approved') "
        "OR (pdf_sha256 IS NOT NULL AND page_count IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_document_versions_approved_is_recorded"),
        "document_versions",
        "(status = 'approved') = (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
    )

    # The typed text of an Other kind or type (§3, §4).
    op.add_column("version_roles", sa.Column("kind_label", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_version_roles_kind_label_length"),
        "version_roles",
        "kind_label IS NULL OR char_length(kind_label) BETWEEN 1 AND 40",
    )
    op.add_column("version_fields", sa.Column("holds_label", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_version_fields_holds_label_when_other"),
        "version_fields",
        "(holds = 'other') = (holds_label IS NOT NULL) "
        "AND (holds_label IS NULL OR char_length(holds_label) BETWEEN 1 AND 60)",
    )

    # Review's own tables: a version's revision, and its metrics once approved (§1.5, §1.6).
    op.create_table(
        "version_reviews",
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("flags", pg.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("baseline_version_id", UUID, nullable=False),
        sa.Column("proposal", pg.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("accepted", pg.JSONB(), nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_version_reviews_revision_positive")),
        sa.ForeignKeyConstraint(
            ["version_id", "workspace_id"],
            ["document_versions.id", "document_versions.workspace_id"],
            name=op.f("fk_version_reviews_version_id_document_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["updated_by", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_version_reviews_updated_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["baseline_version_id", "workspace_id"],
            ["document_versions.id", "document_versions.workspace_id"],
            name=op.f("fk_version_reviews_baseline_version_id_document_versions"),
        ),
        sa.PrimaryKeyConstraint("version_id", name=op.f("pk_version_reviews")),
    )
    # No version has been edited yet, so each one's rows are still the AI's proposal (§1.5).
    op.execute(
        """
        INSERT INTO version_reviews (version_id, workspace_id, flags, baseline_version_id, proposal)
        SELECT r.version_id, r.workspace_id, COALESCE(r.result -> 'flags', '{}'::jsonb),
               r.version_id,
               COALESCE((SELECT jsonb_agg(jsonb_build_object(
                             'page', p.page, 'rect', jsonb_build_array(p.x0, p.y0, p.x1, p.y1),
                             'holds', f.holds, 'label', f.label, 'filled_by', f.filled_by,
                             'party_id', f.role_id))
                         FROM field_placements p JOIN version_fields f ON f.id = p.field_id
                         WHERE p.version_id = r.version_id), '[]'::jsonb)
        FROM detection_runs r
        """
    )
    op.create_table(
        "review_metrics",
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("baseline_version_id", UUID, nullable=False),
        sa.Column("true_positives", sa.Integer(), nullable=False),
        sa.Column("false_positives", sa.Integer(), nullable=False),
        sa.Column("false_negatives", sa.Integer(), nullable=False),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("recall", sa.Float(), nullable=True),
        sa.Column("f1", sa.Float(), nullable=True),
        sa.Column("relabelled", sa.Integer(), nullable=False),
        sa.Column("retyped", sa.Integer(), nullable=False),
        sa.Column("reassigned", sa.Integer(), nullable=False),
        sa.Column("flags_accepted", sa.Integer(), nullable=False),
        sa.Column("mean_iou", sa.Float(), nullable=True),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "workspace_id"],
            ["document_versions.id", "document_versions.workspace_id"],
            name=op.f("fk_review_metrics_version_id_document_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["baseline_version_id", "workspace_id"],
            ["document_versions.id", "document_versions.workspace_id"],
            name=op.f("fk_review_metrics_baseline_version_id_document_versions"),
        ),
        sa.PrimaryKeyConstraint("version_id", name=op.f("pk_review_metrics")),
    )

    # Deleting a field or a party checks no field still refers to it: without these indexes each
    # check reads every field (quadratic in a save, §9.2).
    for column in REFERRING:
        op.create_index(
            f"ix_version_fields_{column}",
            "version_fields",
            [column],
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )

    # An approved version's parties, fields and places never change (NFR-R3). Checked once per
    # statement over every row it touched (transition tables), not once per row: a save writes
    # thousands of rows (NFR-R1). Transition tables need one event per trigger.
    op.execute(
        """
        CREATE FUNCTION review_forbid_approved_rows() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM touched t JOIN document_versions v ON v.id = t.version_id
                       WHERE v.status = 'approved') THEN
                RAISE EXCEPTION 'an approved version''s fields cannot change'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION review_forbid_approved_updates() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM (SELECT version_id FROM touched UNION
                                      SELECT version_id FROM touched_before) t
                       JOIN document_versions v ON v.id = t.version_id
                       WHERE v.status = 'approved') THEN
                RAISE EXCEPTION 'an approved version''s fields cannot change'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    for table in FIELD_TABLES:
        for event, referencing, function in TRIGGERS:
            op.execute(
                f"CREATE TRIGGER {table}_frozen_on_{event.lower()} AFTER {event} ON {table} "
                f"REFERENCING {referencing} FOR EACH STATEMENT EXECUTE FUNCTION {function}()"
            )

    # Current means the newest approved version (§1.1); none is approved yet.
    op.execute("UPDATE documents SET current_version_id = NULL")


def downgrade() -> None:
    for table in FIELD_TABLES:
        for event, _, _ in TRIGGERS:
            op.execute(f"DROP TRIGGER {table}_frozen_on_{event.lower()} ON {table}")
    op.execute("DROP FUNCTION review_forbid_approved_updates()")
    op.execute("DROP FUNCTION review_forbid_approved_rows()")
    for column in REFERRING:
        op.drop_index(f"ix_version_fields_{column}", "version_fields")
    op.drop_table("review_metrics")
    op.drop_table("version_reviews")
    op.drop_constraint(op.f("ck_version_fields_holds_label_when_other"), "version_fields", "check")
    op.drop_column("version_fields", "holds_label")
    op.drop_constraint(op.f("ck_version_roles_kind_label_length"), "version_roles", "check")
    op.drop_column("version_roles", "kind_label")
    op.drop_constraint(
        op.f("ck_document_versions_approved_is_recorded"), "document_versions", type_="check"
    )
    for name in ("status_known", "processed_has_pdf"):
        op.drop_constraint(op.f(f"ck_document_versions_{name}"), "document_versions", type_="check")
    op.execute("UPDATE document_versions SET status = 'ready' WHERE status = 'approved'")
    op.create_check_constraint(
        op.f("ck_document_versions_status_known"),
        "document_versions",
        f"status IN {STATUSES_BEFORE}",
    )
    op.create_check_constraint(
        op.f("ck_document_versions_processed_has_pdf"),
        "document_versions",
        "status NOT IN ('detecting', 'ready') "
        "OR (pdf_sha256 IS NOT NULL AND page_count IS NOT NULL)",
    )
    op.drop_constraint(
        op.f("fk_document_versions_approved_by_users"), "document_versions", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_document_versions_derived_from_version_id_document_versions"),
        "document_versions",
        type_="foreignkey",
    )
    op.drop_column("document_versions", "approved_at")
    op.drop_column("document_versions", "approved_by")
    op.drop_column("document_versions", "derived_from_version_id")
    op.alter_column("document_versions", "description", new_column_name="ai_description")
    op.alter_column("document_versions", "name", new_column_name="ai_name")
