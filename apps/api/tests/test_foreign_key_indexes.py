"""Every foreign key into rows the app deletes has an index starting with its columns.

Deleting a row makes PostgreSQL check each foreign key pointing at it. Without such an index, each
check reads the whole referencing table, so a delete of n rows costs n scans: a review save of
2 000 fields slowed with the size of tables that only ever pointed at approved versions. The check
reads the source for every ``DELETE FROM``, follows ``ON DELETE CASCADE`` (a delete there deletes
here too), and asks the migrated database which keys into those tables lack an index.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Engine, text

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "signora"
DELETE = re.compile(r"DELETE FROM ([a-z_]+)")


def deleted_tables() -> set[str]:
    found: set[str] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        if "migrations" not in path.parts:
            found |= set(DELETE.findall(path.read_text()))
    return found


FOREIGN_KEYS = """
    SELECT c.conname, c.conrelid::regclass::text AS referencing,
           c.confrelid::regclass::text AS referenced, c.confdeltype = 'c' AS cascades,
           -- An index Postgres can use for the key's check (``col1 = $1 AND col2 = $2``): valid,
           -- not partial (a partial one cannot serve every row), and leading with one of the key's
           -- columns (it finds the rows by that one and checks the others among them).
           EXISTS (
               SELECT 1 FROM pg_index i
               WHERE i.indrelid = c.conrelid AND i.indisvalid AND i.indpred IS NULL
                 AND (string_to_array(i.indkey::text, ' ')::int2[])[1] = ANY(c.conkey)
           ) AS indexed
    FROM pg_constraint c WHERE c.contype = 'f'
"""


def test_every_foreign_key_into_deleted_rows_is_indexed(engine: Engine) -> None:
    with engine.connect() as connection:
        keys = connection.execute(text(FOREIGN_KEYS)).all()
    deleted = deleted_tables()
    assert "version_fields" in deleted  # the source was read: a review save replaces its fields
    while True:  # rows a cascade deletes are deleted rows too
        more = {k.referencing for k in keys if k.cascades and k.referenced in deleted} - deleted
        if not more:
            break
        deleted |= more

    unindexed = sorted(
        f"{k.conname} ({k.referencing} -> {k.referenced})"
        for k in keys
        if k.referenced in deleted and not k.indexed
    )

    assert unindexed == []
