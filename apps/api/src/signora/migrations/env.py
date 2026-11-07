"""Alembic environment. Online migrations only; the URL comes from the application settings."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from signora import models  # noqa: F401  (imports every module's tables into the metadata)
from signora.kernel.db import metadata

config = context.config


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    if url is None:
        raise RuntimeError("sqlalchemy.url is not set; run migrations through signora.kernel")
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline (SQL script) migrations are not supported")
run_migrations_online()
