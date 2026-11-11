"""Shared fixtures (backbone LLD §9.3).

A dedicated ``signora_test`` database (or ``SIGNORA_TEST_DATABASE``) on the compose Postgres is
recreated once per test session and migrated to head. ``db`` gives a unit-of-work factory whose
work is rolled back after each test;
``committing_db`` commits for real (concurrency tests), using unique ids so tests never collide.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text

from signora.handlers import register_all
from signora.kernel.config import DatabaseSettings, load_settings
from signora.kernel.db import Database, create_db_engine
from signora.kernel.jobs import core as jobs_core
from signora.kernel.migrations import upgrade_to_head

# The test database's name. Tests drop and recreate it, so two checkouts running tests at once
# (worktrees of parallel branches) each set SIGNORA_TEST_DATABASE to a name of their own.
TEST_DATABASE = os.environ.get("SIGNORA_TEST_DATABASE", "signora_test")


@pytest.fixture(scope="session", autouse=True)
def registered_job_kinds() -> None:
    """Every process registers the job kinds at start-up (handlers.py); so does the test session."""
    register_all(jobs_core.registry)


@pytest.fixture(scope="session")
def test_db_settings() -> DatabaseSettings:
    base = load_settings().db
    return base.model_copy(update={"name": TEST_DATABASE})


@pytest.fixture(scope="session")
def engine(test_db_settings: DatabaseSettings) -> Iterator[Engine]:
    admin_url = test_db_settings.model_copy(update={"name": "postgres"}).url
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE}"'))
    admin.dispose()

    upgrade_to_head(test_db_settings)
    test_engine = create_db_engine(test_db_settings, pool_size=10)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Database]:
    """Units of work inside one outer transaction that is rolled back after the test."""
    with engine.connect() as connection:
        outer = connection.begin()
        yield Database(connection)
        outer.rollback()


@pytest.fixture
def committing_db(engine: Engine) -> Database:
    """Units of work that really commit. Use unique ids; the database is recreated per session."""
    return Database(engine)


@pytest.fixture
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry failed jobs immediately instead of waiting for backoff."""
    monkeypatch.setattr(jobs_core, "backoff_seconds", lambda attempt: 0.0)
