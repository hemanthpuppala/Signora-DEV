"""Schema migrations (Alembic), run programmatically so the CLI, readiness and worker share them.

Migration scripts live in the ``signora.migrations`` package so they ship inside the installed
package and container image.
"""

from __future__ import annotations

from importlib.resources import files

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from signora.kernel.config import DatabaseSettings


def alembic_config(settings: DatabaseSettings) -> Config:
    config = Config()
    config.set_main_option("script_location", str(files("signora.migrations")))
    # ConfigParser interpolation treats "%" specially; escape it in the URL.
    config.set_main_option("sqlalchemy.url", settings.url.replace("%", "%%"))
    return config


def upgrade_to_head(settings: DatabaseSettings) -> None:
    command.upgrade(alembic_config(settings), "head")


def head_revisions(settings: DatabaseSettings) -> set[str]:
    return set(ScriptDirectory.from_config(alembic_config(settings)).get_heads())


def current_revisions(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(MigrationContext.configure(connection).get_current_heads())


def migrations_at_head(engine: Engine, settings: DatabaseSettings) -> bool:
    """True when the database schema matches the latest migration."""
    return current_revisions(engine) == head_revisions(settings)
