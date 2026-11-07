"""Database, unit of work and migration tests (backbone LLD task 1.3)."""

from __future__ import annotations

import threading
import uuid

import pytest
import sqlalchemy.exc
from alembic import command
from sqlalchemy import Engine, create_engine, text

from signora.kernel.config import DatabaseSettings
from signora.kernel.db import Database, create_db_engine
from signora.kernel.migrations import (
    alembic_config,
    current_revisions,
    head_revisions,
    migrations_at_head,
)


class _BoomError(Exception):
    pass


def _insert_job(uow_db: Database, kind: str) -> None:
    with uow_db.unit_of_work() as uow:
        uow.session.execute(text("INSERT INTO jobs (kind) VALUES (:kind)"), {"kind": kind})


def _count_jobs(uow_db: Database, kind: str) -> int:
    with uow_db.unit_of_work() as uow:
        return int(
            uow.session.execute(
                text("SELECT count(*) FROM jobs WHERE kind = :kind"), {"kind": kind}
            ).scalar_one()
        )


def test_migrations_are_at_head(engine: Engine, test_db_settings: DatabaseSettings) -> None:
    assert current_revisions(engine) == head_revisions(test_db_settings) == {"0001"}
    assert migrations_at_head(engine, test_db_settings)


def test_backbone_tables_exist_with_uuidv7_ids(db: Database) -> None:
    with db.unit_of_work() as uow:
        tables = set(
            uow.session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )
        job_id = uow.session.execute(
            text("INSERT INTO jobs (kind) VALUES ('t') RETURNING id")
        ).scalar_one()

    assert {"jobs", "idempotency_keys", "audit_events", "alembic_version"} <= tables
    assert isinstance(job_id, uuid.UUID)
    assert job_id.version == 7


def test_unit_of_work_commits_on_success(committing_db: Database) -> None:
    kind = f"commit-{uuid.uuid4()}"
    _insert_job(committing_db, kind)
    assert _count_jobs(committing_db, kind) == 1


def test_unit_of_work_rolls_back_on_exception(committing_db: Database) -> None:
    kind = f"rollback-{uuid.uuid4()}"
    with pytest.raises(_BoomError), committing_db.unit_of_work() as uow:
        uow.session.execute(text("INSERT INTO jobs (kind) VALUES (:kind)"), {"kind": kind})
        raise _BoomError
    assert _count_jobs(committing_db, kind) == 0


def test_commit_then_raise_persists_the_outcome(committing_db: Database) -> None:
    """LLD §7.1a: an outcome committed before raising survives the error."""
    kind = f"persisted-{uuid.uuid4()}"
    after = f"after-{uuid.uuid4()}"
    with pytest.raises(_BoomError), committing_db.unit_of_work() as uow:
        uow.session.execute(text("INSERT INTO jobs (kind) VALUES (:kind)"), {"kind": kind})
        uow.commit()
        uow.session.execute(text("INSERT INTO jobs (kind) VALUES (:kind)"), {"kind": after})
        raise _BoomError
    assert _count_jobs(committing_db, kind) == 1
    assert _count_jobs(committing_db, after) == 0  # work after the commit is rolled back


def test_rollback_fixture_isolates_tests(db: Database) -> None:
    _insert_job(db, "isolated")
    assert _count_jobs(db, "isolated") == 1  # visible inside the test; rolled back afterwards


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET action = 'x'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
def test_audit_events_reject_changes(committing_db: Database, statement: str) -> None:
    chain = uuid.uuid4()
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "INSERT INTO audit_events (chain_kind, chain_id, seq, workspace_id, occurred_at,"
                " actor_type, action, hash) VALUES ('workspace', :c, 1, :c, now(), 'system',"
                " 'test.recorded', :h)"
            ),
            {"c": chain, "h": bytes(32)},
        )
    with (
        pytest.raises(sqlalchemy.exc.DBAPIError, match="append-only"),
        committing_db.unit_of_work() as uow,
    ):
        uow.session.execute(text(statement))


def test_pool_fails_fast_when_exhausted(test_db_settings: DatabaseSettings) -> None:
    small = create_db_engine(test_db_settings, pool_size=1, pool_timeout=0.5)
    held = threading.Event()
    release = threading.Event()

    def hold_connection() -> None:
        with small.connect():
            held.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_connection)
    holder.start()
    try:
        assert held.wait(timeout=5)
        with pytest.raises(sqlalchemy.exc.TimeoutError), small.connect():
            pass
    finally:
        release.set()
        holder.join()
        small.dispose()


def test_migrations_downgrade_and_upgrade_cleanly(test_db_settings: DatabaseSettings) -> None:
    """Every migration is reversible: base -> head -> base -> head on a throwaway database."""
    name = f"signora_roundtrip_{uuid.uuid4().hex[:8]}"
    admin = create_engine(
        test_db_settings.model_copy(update={"name": "postgres"}).url, isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    settings = test_db_settings.model_copy(update={"name": name})
    try:
        config = alembic_config(settings)
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        probe = create_db_engine(settings, pool_size=1)
        assert migrations_at_head(probe, settings)
        probe.dispose()
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
