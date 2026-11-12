"""A company's website and its logo (Company logo LLD §6).

The website is kept as its domain; the logo found for it is a blob of the workspace, set by a
background job, and looked up again when ``logo_check_due_at`` comes (a sweep queues those).
Both are optional: a company without them shows its name.

Numbered after 0027 and 0028, written on a parallel branch from the same 0026; merged after them,
it follows 0028.

Revision ID: 0029
Revises: 0026
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# All migrations run in one transaction, and 0003 inserts the system workspace under this deferred
# foreign key: Postgres refuses to alter a table with checks still pending. Running them first
# (they pass) and deferring the constraint again afterwards leaves its behaviour as declared.
_CREATOR_FK = "fk_workspaces_created_by_users"


def upgrade() -> None:
    op.execute(f"SET CONSTRAINTS {_CREATOR_FK} IMMEDIATE")
    op.add_column("workspaces", sa.Column("website", sa.Text(), nullable=True))
    op.add_column("workspaces", sa.Column("logo_sha256", sa.Text(), nullable=True))
    op.add_column("workspaces", sa.Column("logo_bytes", sa.Integer(), nullable=True))
    op.add_column("workspaces", sa.Column("logo_etag", sa.Text(), nullable=True))
    op.add_column(
        "workspaces", sa.Column("logo_check_due_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_workspaces_website_length"),
        "workspaces",
        "char_length(website) BETWEEN 4 AND 253",
    )
    op.create_check_constraint(
        op.f("ck_workspaces_logo_complete"),
        "workspaces",
        "(logo_sha256 IS NULL) = (logo_bytes IS NULL) "
        "AND (logo_sha256 IS NULL OR website IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_workspaces_logo_check_has_website"),
        "workspaces",
        "logo_check_due_at IS NULL OR website IS NOT NULL",
    )
    op.create_index(
        "ix_workspaces_logo_check_due_at",
        "workspaces",
        ["logo_check_due_at"],
        postgresql_where=sa.text("logo_check_due_at IS NOT NULL"),
    )
    op.execute(f"SET CONSTRAINTS {_CREATOR_FK} DEFERRED")


def downgrade() -> None:
    op.drop_index("ix_workspaces_logo_check_due_at", table_name="workspaces")
    op.drop_constraint(op.f("ck_workspaces_logo_check_has_website"), "workspaces", type_="check")
    op.drop_constraint(op.f("ck_workspaces_logo_complete"), "workspaces", type_="check")
    op.drop_constraint(op.f("ck_workspaces_website_length"), "workspaces", type_="check")
    for column in ("logo_check_due_at", "logo_etag", "logo_bytes", "logo_sha256", "website"):
        op.drop_column("workspaces", column)
