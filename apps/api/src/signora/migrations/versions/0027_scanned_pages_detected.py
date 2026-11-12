"""Scanned pages are detected (Phase 5c).

A version with pages that are pictures is no longer stopped at ``needs_ocr``: its lines are read
from its pixels and the AI reads the pictures (``05c-scanned-documents.md``). Every version left at
``needs_ocr`` becomes ``detecting`` with its detection queued, as the event would have done, the way
0016 queued the processed versions. The status stays allowed: nothing sets it any more.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The queued jobs' dedupe keys end with "scanned-0027", so the downgrade finds them (matched
# without a colon before it: in SQL text, ":word" is read as a bind parameter).


def upgrade() -> None:
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
               'event:' || e.event_id || ':detection:scanned-0027'
        FROM document_versions v
        CROSS JOIN LATERAL (SELECT gen_random_uuid() AS event_id) e
        WHERE v.status = 'needs_ocr'
        """
    )
    op.execute("UPDATE document_versions SET status = 'detecting' WHERE status = 'needs_ocr'")


def downgrade() -> None:
    op.execute(
        """
        UPDATE document_versions SET status = 'needs_ocr'
        WHERE id IN (
            SELECT (payload ->> 'version_id')::uuid FROM jobs
            WHERE dedupe_key LIKE '%scanned-0027'
        ) AND status = 'detecting'
        """
    )
    op.execute("DELETE FROM jobs WHERE dedupe_key LIKE '%scanned-0027'")
