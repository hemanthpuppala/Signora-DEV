"""Department settings: reminders, expiry, extra notify emails (Phase 3 LLD topic 3).

Existing departments get the built-in defaults (24 h, 5, 14 days); new ones are created with the
company defaults by the application.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS = {
    "reminder_interval_hours_range": "reminder_interval_hours BETWEEN 1 AND 720",
    "max_reminders_range": "max_reminders BETWEEN 0 AND 20",
    "expiry_days_range": "expiry_days BETWEEN 1 AND 365",
    "notify_emails_count": "cardinality(notify_emails) <= 5",
}


def upgrade() -> None:
    for name, default in (
        ("reminder_interval_hours", "24"),
        ("max_reminders", "5"),
        ("expiry_days", "14"),
    ):
        op.add_column(
            "departments",
            sa.Column(name, sa.Integer(), server_default=sa.text(default), nullable=False),
        )
    op.add_column(
        "departments",
        sa.Column(
            "notify_emails",
            pg.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
    )
    for name, condition in CHECKS.items():
        op.create_check_constraint(name, "departments", condition)


def downgrade() -> None:
    for name in CHECKS:
        # op.f: the name is already final; without it the naming convention prefixes it again.
        op.drop_constraint(op.f(f"ck_departments_{name}"), "departments", type_="check")
    for column in ("notify_emails", "expiry_days", "max_reminders", "reminder_interval_hours"):
        op.drop_column("departments", column)
