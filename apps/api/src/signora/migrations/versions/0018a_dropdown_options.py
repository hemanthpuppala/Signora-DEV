"""A dropdown's or a list's options, kept with its place (Phase 6 LLD §15.3).

A radio group has a place per option; a dropdown or a list is one place, so its options had no
home in review's tables and existed only in detection's reading of the PDF. Review could not check
a condition on one, nor offer one. They are kept on the place, as the PDF gives them.

Places already stored take their options from their version's reading (a version made by editing:
the reading of the version it was detected as). They are facts of the PDF, so approved versions
take them too: the trigger that freezes an approved version's places is off for this one statement.

Revision ID: 0018a
Revises: 0018
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0018a"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FROZEN = "field_placements_frozen_on_update"


# The options of the places already stored, from their version's reading of the PDF.
FILL = (
    f"ALTER TABLE field_placements DISABLE TRIGGER {FROZEN}",
    """
    UPDATE field_placements p SET options = found.options
    FROM version_reviews r, detection_runs d,
         LATERAL (SELECT f -> 'options' AS options, f ->> 'pdf_field' AS pdf_field
                  FROM jsonb_array_elements(d.parsed -> 'fields') AS f
                  WHERE f ->> 'kind' IN ('combobox', 'listbox')) AS found
    WHERE p.kind IN ('combobox', 'listbox')
      AND p.options IS NULL
      AND r.version_id = p.version_id
      AND d.version_id = COALESCE(r.baseline_version_id, p.version_id)
      AND found.pdf_field = p.pdf_field
      AND jsonb_typeof(found.options) = 'array'
    """,
    f"ALTER TABLE field_placements ENABLE TRIGGER {FROZEN}",
)


def upgrade() -> None:
    op.add_column("field_placements", sa.Column("options", pg.JSONB))
    for statement in FILL:
        op.execute(statement)


def downgrade() -> None:
    op.drop_column("field_placements", "options")
