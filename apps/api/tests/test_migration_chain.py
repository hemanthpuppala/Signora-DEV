"""The migrations have exactly one head.

Two branches written from the same parent each add the next migration; whichever merges second
must follow the other. If it does not, ``alembic upgrade head`` refuses the deploy (two heads).
"""

from __future__ import annotations

from alembic.script import ScriptDirectory

from signora.kernel.config import DatabaseSettings
from signora.kernel.migrations import alembic_config


def test_the_migrations_have_one_head(test_db_settings: DatabaseSettings) -> None:
    heads = ScriptDirectory.from_config(alembic_config(test_db_settings)).get_heads()

    assert len(heads) == 1, heads
