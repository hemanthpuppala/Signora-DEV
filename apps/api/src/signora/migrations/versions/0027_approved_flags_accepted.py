"""Approving accepts every "needs a look" flag (Phase 6 §2.2): clear the flags still kept on
versions approved before approval cleared them.

Each such flag was counted as accepted when its version was approved (``review_metrics``), so
nothing the approval recorded changes. Approved versions' fields are frozen by a trigger; it is
set aside for this one statement, in this transaction, and back before it ends. The downgrade
cannot bring the flags back: they were resolved by the approvals.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FROZEN = "version_fields_frozen_on_update"


def upgrade() -> None:
    op.execute(f"ALTER TABLE version_fields DISABLE TRIGGER {FROZEN}")
    op.execute(
        "UPDATE version_fields f SET needs_review = NULL FROM document_versions v "
        "WHERE v.id = f.version_id AND v.status = 'approved' AND f.needs_review IS NOT NULL"
    )
    op.execute(f"ALTER TABLE version_fields ENABLE TRIGGER {FROZEN}")


def downgrade() -> None:
    """Nothing to undo: the cleared flags were resolved by their approvals."""
