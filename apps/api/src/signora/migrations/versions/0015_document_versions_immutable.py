"""Stored document versions never change (Phase 4 LLD §4.3, platform §9).

What a version was made from (its upload) never changes; what processing produced (working copy,
page facts) and the unlocked copy are fixed once recorded; versions are never deleted. Status,
failure details and the AI description may still change. Enforced in the database, so the rule
holds outside the application code too.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION document_versions_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'document versions are never deleted'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF (NEW.id, NEW.workspace_id, NEW.document_id, NEW.version_no, NEW.source_sha256,
                NEW.source_kind, NEW.source_filename, NEW.source_bytes, NEW.ai_instructions,
                NEW.uploaded_by, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.workspace_id, OLD.document_id, OLD.version_no, OLD.source_sha256,
                OLD.source_kind, OLD.source_filename, OLD.source_bytes, OLD.ai_instructions,
                OLD.uploaded_by, OLD.created_at)
            THEN
                RAISE EXCEPTION 'what a document version was made from never changes'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF OLD.unlocked_sha256 IS NOT NULL
               AND NEW.unlocked_sha256 IS DISTINCT FROM OLD.unlocked_sha256
            THEN
                RAISE EXCEPTION 'an unlocked copy never changes'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF OLD.pdf_sha256 IS NOT NULL
               AND (NEW.pdf_sha256, NEW.pdf_bytes, NEW.page_count, NEW.pages,
                    NEW.pages_without_text, NEW.processed_at)
                   IS DISTINCT FROM
                   (OLD.pdf_sha256, OLD.pdf_bytes, OLD.page_count, OLD.pages,
                    OLD.pages_without_text, OLD.processed_at)
            THEN
                RAISE EXCEPTION 'a processed document version never changes'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER document_versions_immutable
        BEFORE UPDATE OR DELETE ON document_versions
        FOR EACH ROW EXECUTE FUNCTION document_versions_immutable()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS document_versions_immutable ON document_versions")
    op.execute("DROP FUNCTION IF EXISTS document_versions_immutable()")
