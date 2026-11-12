"""Search (ADR S-1): pg_trgm, and a trigram index on every column a list searches.

Templates by name; envelopes by title; their people by name and email. A GIN ``gin_trgm_ops``
index serves both halves of a match (``ILIKE '%q%'`` and the word similarity ``q <% text``).

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = (
    ("ix_documents_name_trgm", "documents", "name"),
    ("ix_envelopes_title_trgm", "envelopes", "title"),
    ("ix_envelope_recipients_name_trgm", "envelope_recipients", "name"),
    ("ix_envelope_recipients_email_trgm", "envelope_recipients", "email"),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in INDEXES:
        op.execute(f"CREATE INDEX {name} ON {table} USING gin ({column} gin_trgm_ops)")


def downgrade() -> None:
    for name, _, _ in INDEXES:
        op.execute(f"DROP INDEX {name}")
    # The extension stays: dropping it could break anything else that came to rely on it.
