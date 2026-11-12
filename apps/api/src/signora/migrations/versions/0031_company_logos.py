"""One logo per domain (Company logo LLD §6, revised): ``company_logos``, shared by every company on
a domain and kept when they are gone, so a company on a known domain shows its logo without asking
logo.dev. The website becomes its registrable domain ("app.scoutboard.com" is "scoutboard.com").

Each website is reduced as the website rule now does it (the bundled Public Suffix List, offline)
and its domain gets a row with a look-up due now. The logos kept per workspace are not carried
over: their files are in each workspace's store, a domain's is in the system's; each is looked up
once more. The downgrade puts the columns back empty and drops the shared logos.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import tldextract
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Migration 0003's system-workspace row leaves this deferred check pending, and Postgres refuses to
# alter a table with checks pending (all migrations run in one transaction): run it, then defer it.
_CREATOR_FK = "fk_workspaces_created_by_users"


def upgrade() -> None:
    op.execute(f"SET CONSTRAINTS {_CREATOR_FK} IMMEDIATE")
    op.create_table(
        "company_logos",
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("logo_sha256", sa.Text(), nullable=True),
        sa.Column("logo_bytes", sa.Integer(), nullable=True),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(domain) BETWEEN 4 AND 253", name=op.f("ck_company_logos_domain_length")
        ),
        sa.CheckConstraint(
            "(logo_sha256 IS NULL) = (logo_bytes IS NULL)",
            name=op.f("ck_company_logos_logo_complete"),
        ),
        sa.PrimaryKeyConstraint("domain", name=op.f("pk_company_logos")),
    )
    op.create_index(
        "ix_company_logos_check_due_at",
        "company_logos",
        ["check_due_at"],
        postgresql_where=sa.text("check_due_at IS NOT NULL"),
    )

    suffixes = tldextract.TLDExtract(
        suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, website FROM workspaces WHERE website IS NOT NULL")
    ).all()
    for row in rows:
        domain = suffixes(row.website).top_domain_under_public_suffix or None
        connection.execute(
            sa.text("UPDATE workspaces SET website = :d WHERE id = :w"), {"d": domain, "w": row.id}
        )
    op.execute(
        "INSERT INTO company_logos (domain, check_due_at) "
        "SELECT DISTINCT website, now() FROM workspaces WHERE website IS NOT NULL"
    )

    op.drop_index("ix_workspaces_logo_check_due_at", table_name="workspaces")
    op.drop_constraint(op.f("ck_workspaces_logo_check_has_website"), "workspaces", type_="check")
    op.drop_constraint(op.f("ck_workspaces_logo_complete"), "workspaces", type_="check")
    for column in ("logo_check_due_at", "logo_etag", "logo_bytes", "logo_sha256"):
        op.drop_column("workspaces", column)
    op.create_index(
        "ix_workspaces_website",
        "workspaces",
        ["website"],
        postgresql_where=sa.text("website IS NOT NULL"),
    )
    op.execute(f"SET CONSTRAINTS {_CREATOR_FK} DEFERRED")


def downgrade() -> None:
    op.execute(f"SET CONSTRAINTS {_CREATOR_FK} IMMEDIATE")
    op.drop_index("ix_workspaces_website", table_name="workspaces")
    op.add_column("workspaces", sa.Column("logo_sha256", sa.Text(), nullable=True))
    op.add_column("workspaces", sa.Column("logo_bytes", sa.Integer(), nullable=True))
    op.add_column("workspaces", sa.Column("logo_etag", sa.Text(), nullable=True))
    op.add_column(
        "workspaces", sa.Column("logo_check_due_at", sa.DateTime(timezone=True), nullable=True)
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
    op.execute("UPDATE workspaces SET logo_check_due_at = now() WHERE website IS NOT NULL")
    op.drop_index("ix_company_logos_check_due_at", table_name="company_logos")
    op.drop_table("company_logos")
    op.execute(f"SET CONSTRAINTS {_CREATOR_FK} DEFERRED")
