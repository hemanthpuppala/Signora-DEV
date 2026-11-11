"""Join the two lines of migrations after 0018 (Phase 6 LLD §15.3).

Phase 7's migrations (0019 to 0022) and the dropdown options (0018a) both follow 0018. This
revision changes nothing: it gives the history one head again, so a database that already has
Phase 7's migrations takes 0018a on its way here, and a new one takes both lines.

Revision ID: 0023
Revises: 0022, 0018a
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0023"
down_revision: tuple[str, str] = ("0022", "0018a")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two lines meet here."""


def downgrade() -> None:
    """Nothing to change: the two lines part here."""
