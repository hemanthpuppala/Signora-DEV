"""Dates as the document writes them (Phase 7c LLD).

A field holding a date or a part of one records how its blank writes it: a whole date's order and
length, a day as a number or "9th", a month as a name or a number, a year in four digits or two.
Null for other types, and for fields written before: they read as their type's default.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("version_fields", sa.Column("format", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("version_fields", "format")
