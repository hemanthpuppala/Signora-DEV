"""Job queue tests (backbone LLD §1.9).

Each test registers its own uniquely named job kinds in a fresh registry. Workers only claim kinds
they have registered, so tests sharing the database never touch each other's jobs.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy import create_engine, text

from signora.entrypoints import worker as worker_entrypoint
from signora.kernel.config import DatabaseSettings, load_settings
from signora.kernel.db import Database
from signora.kernel.jobs import (
    JobContext,
    JobKind,
    JobRegistry,
    LeaseLostError,
    RecurringJob,
    UnknownJobKindError,
    enqueue,
    housekeeping,
)
from signora.kernel.jobs import core as jobs_core
from signora.kernel.jobs.core import NOTIFY_CHANNEL, claim, reclaim_expired
from signora.kernel.logging import bind_context, clear_context
from tests.support.workers import running_worker, wait_until


def unique_kind(label: str) -> str:
    return f"test.{label}.{uuid.uuid4().hex[:8]}"


def job_rows(db: Database, kind: str) -> list[Any]:
    with db.unit_of_work() as uow:
        return list(
            uow.session.execute(
                text("SELECT * FROM jobs WHERE kind = :kind ORDER BY created_at"), {"kind": kind}
            ).all()
        )


def register(
    reg: JobRegistry,
    kind: str,
    handler: Callable[[JobContext], None],
    *,
    max_attempts: int = 3,
    lease: timedelta = timedelta(seconds=30),
) -> None:
    reg.register(JobKind(kind, handler, max_attempts=max_attempts, lease=lease))


def test_enqueue_is_rolled_back_with_its_transaction(committing_db: Database) -> None:
    reg = JobRegistry()
    kind = unique_kind("rollback")
    register(reg, kind, lambda ctx: None)

    with pytest.raises(RuntimeError), committing_db.unit_of_work() as uow:
        enqueue(uow.session, kind, jobs_registry=reg)
        raise RuntimeError

    assert job_rows(committing_db, kind) == []


def test_unknown_kind_is_rejected(committing_db: Database) -> None:
    with pytest.raises(UnknownJobKindError), committing_db.unit_of_work() as uow:
        enqueue(uow.session, "test.never-registered", jobs_registry=JobRegistry())


def test_dedupe_key_keeps_one_row_even_under_concurrency(committing_db: Database) -> None:
    reg = JobRegistry()
    kind = unique_kind("dedupe")
    register(reg, kind, lambda ctx: None)
    results: list[bool] = []
    lock = threading.Lock()

    def add() -> None:
        with committing_db.unit_of_work() as uow:
            added = enqueue(uow.session, kind, dedupe_key=f"{kind}:only", jobs_registry=reg)
        with lock:
            results.append(added)

    threads = [threading.Thread(target=add) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1
    assert len(job_rows(committing_db, kind)) == 1


def test_notification_is_delivered_only_on_commit(
    committing_db: Database, test_db_settings: DatabaseSettings
) -> None:
    reg = JobRegistry()
    kind = unique_kind("notify")
    register(reg, kind, lambda ctx: None)

    with psycopg.connect(test_db_settings.conninfo, autocommit=True) as listener:
        listener.execute(f"LISTEN {NOTIFY_CHANNEL}")
        with committing_db.unit_of_work() as uow:
            enqueue(uow.session, kind, jobs_registry=reg)
            before_commit = [n.payload for n in listener.notifies(timeout=0.3)]
        after_commit = [n.payload for n in listener.notifies(timeout=2.0, stop_after=1)]

    assert kind not in before_commit
    assert after_commit == [kind]


def test_request_id_from_log_context_is_stored_in_meta(committing_db: Database) -> None:
    reg = JobRegistry()
    kind = unique_kind("meta")
    register(reg, kind, lambda ctx: None)
    bind_context(request_id="req-1234-abcd")
    try:
        with committing_db.unit_of_work() as uow:
            enqueue(uow.session, kind, {"n": 1}, jobs_registry=reg)
    finally:
        clear_context()

    (row,) = job_rows(committing_db, kind)
    assert row.meta == {"request_id": "req-1234-abcd"}
    assert row.payload == {"n": 1}


def test_two_workers_run_every_job_exactly_once(
    committing_db: Database, test_db_settings: DatabaseSettings
) -> None:
    reg = JobRegistry()
    kind = unique_kind("exactly-once")
    seen: Counter[int] = Counter()
    lock = threading.Lock()

    def handler(ctx: JobContext) -> None:
        with lock:
            seen[int(ctx.payload["n"])] += 1

    register(reg, kind, handler)
    with committing_db.unit_of_work() as uow:
        for n in range(200):
            enqueue(uow.session, kind, {"n": n}, jobs_registry=reg)

    with (
        running_worker(committing_db, test_db_settings, reg),
        running_worker(committing_db, test_db_settings, reg),
    ):
        wait_until(lambda: sum(seen.values()) >= 200, timeout=30)

    assert seen == Counter(range(200))
    assert {row.status for row in job_rows(committing_db, kind)} == {"succeeded"}


def test_failing_job_retries_then_goes_dead(
    committing_db: Database, test_db_settings: DatabaseSettings, no_backoff: None
) -> None:
    reg = JobRegistry()
    kind = unique_kind("always-fails")

    def handler(ctx: JobContext) -> None:
        raise ValueError(f"boom on attempt {ctx.attempt}")

    register(reg, kind, handler, max_attempts=3)
    with committing_db.unit_of_work() as uow:
        enqueue(uow.session, kind, jobs_registry=reg)

    with running_worker(committing_db, test_db_settings, reg):
        wait_until(lambda: job_rows(committing_db, kind)[0].status == "dead")

    (row,) = job_rows(committing_db, kind)
    assert row.attempts == 3
    assert row.last_error == "ValueError: boom on attempt 3"
    assert row.finished_at is not None


def test_backoff_doubles_with_jitter_and_caps() -> None:
    first, third, huge = (jobs_core.backoff_seconds(a) for a in (1, 3, 40))
    assert 24 <= first <= 36
    assert 96 <= third <= 144
    assert huge <= 3600 * 1.2


def test_job_that_fails_once_succeeds_on_retry(
    committing_db: Database, test_db_settings: DatabaseSettings, no_backoff: None
) -> None:
    reg = JobRegistry()
    kind = unique_kind("flaky")

    def handler(ctx: JobContext) -> None:
        if ctx.attempt == 1:
            raise ConnectionError("temporary")

    register(reg, kind, handler)
    with committing_db.unit_of_work() as uow:
        enqueue(uow.session, kind, jobs_registry=reg)

    with running_worker(committing_db, test_db_settings, reg):
        wait_until(lambda: job_rows(committing_db, kind)[0].status == "succeeded")

    assert job_rows(committing_db, kind)[0].attempts == 2


def test_job_of_a_crashed_worker_is_reclaimed_after_its_lease(
    committing_db: Database, test_db_settings: DatabaseSettings
) -> None:
    reg = JobRegistry()
    kind = unique_kind("reclaim")
    done = threading.Event()
    register(reg, kind, lambda ctx: done.set(), lease=timedelta(seconds=1))
    with committing_db.unit_of_work() as uow:
        enqueue(uow.session, kind, jobs_registry=reg)
    with committing_db.unit_of_work() as uow:  # a worker claims it and then "crashes"
        assert len(claim(uow.session, reg, 1)) == 1

    with running_worker(committing_db, test_db_settings, reg):
        assert done.wait(timeout=10)
        wait_until(lambda: job_rows(committing_db, kind)[0].status == "succeeded")

    assert job_rows(committing_db, kind)[0].attempts == 2


def test_long_running_job_keeps_its_lease(
    committing_db: Database, test_db_settings: DatabaseSettings
) -> None:
    reg = JobRegistry()
    kind = unique_kind("long")
    runs = Counter[str]()

    def handler(ctx: JobContext) -> None:
        runs["calls"] += 1
        time.sleep(5)  # longer than the 3 s lease; renewals keep it

    register(reg, kind, handler, lease=timedelta(seconds=3))
    with committing_db.unit_of_work() as uow:
        enqueue(uow.session, kind, jobs_registry=reg)

    with (
        running_worker(committing_db, test_db_settings, reg),
        running_worker(committing_db, test_db_settings, reg),
    ):
        wait_until(lambda: job_rows(committing_db, kind)[0].status == "succeeded", timeout=20)

    assert runs["calls"] == 1
    assert job_rows(committing_db, kind)[0].attempts == 1


def test_stale_worker_cannot_complete_a_reclaimed_job(committing_db: Database) -> None:
    reg = JobRegistry()
    kind = unique_kind("stale")
    register(reg, kind, lambda ctx: None, lease=timedelta(seconds=30))
    with committing_db.unit_of_work() as uow:
        enqueue(uow.session, kind, jobs_registry=reg)
    with committing_db.unit_of_work() as uow:
        (first,) = claim(uow.session, reg, 1)
        uow.session.execute(
            text("UPDATE jobs SET lease_expires_at = now() - interval '1 second' WHERE id = :id"),
            {"id": first.id},
        )
    with committing_db.unit_of_work() as uow:
        assert reclaim_expired(uow.session, reg) == (1, 0)
    with committing_db.unit_of_work() as uow:
        (second,) = claim(uow.session, reg, 1)
    marker = f"stale-write-{uuid.uuid4()}"
    stale = JobContext(first.id, kind, first.payload, first.meta, first.attempt, committing_db)

    with pytest.raises(LeaseLostError), stale.complete() as uow:
        uow.session.execute(text("INSERT INTO jobs (kind) VALUES (:k)"), {"k": marker})

    assert second.attempt == 2
    assert job_rows(committing_db, kind)[0].status == "running"
    assert job_rows(committing_db, marker) == []  # the stale worker's writes were rolled back


def test_handler_holds_no_transaction_during_slow_work(
    committing_db: Database, test_db_settings: DatabaseSettings
) -> None:
    reg = JobRegistry()
    kind = unique_kind("slow-io")
    in_handler = threading.Event()
    release = threading.Event()

    def handler(ctx: JobContext) -> None:
        in_handler.set()
        release.wait(timeout=5)  # stands in for an AI or SMTP call

    register(reg, kind, handler)
    with committing_db.unit_of_work() as uow:
        enqueue(uow.session, kind, jobs_registry=reg)

    with running_worker(committing_db, test_db_settings, reg):
        assert in_handler.wait(timeout=10)
        with committing_db.unit_of_work() as uow:
            idle_in_transaction = uow.session.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                    " AND state = 'idle in transaction'"
                )
            ).scalar_one()
        release.set()

    assert idle_in_transaction == 0


def test_housekeeping_deletes_only_old_succeeded_jobs(committing_db: Database) -> None:
    reg = JobRegistry()
    housekeeping.register(reg)
    label = unique_kind("hk")
    with committing_db.unit_of_work() as uow:
        for suffix, status, age_days in (
            ("old-ok", "succeeded", 8),
            ("new-ok", "succeeded", 1),
            ("old-dead", "dead", 30),
        ):
            uow.session.execute(
                text(
                    "INSERT INTO jobs (kind, status, finished_at)"
                    " VALUES (:k, :s, now() - make_interval(days => :d))"
                ),
                {"k": f"{label}.{suffix}", "s": status, "d": age_days},
            )
        enqueue(
            uow.session,
            housekeeping.HOUSEKEEPING,
            dedupe_key=f"hk-test-{label}",
            jobs_registry=reg,
        )
    with committing_db.unit_of_work() as uow:
        (job,) = claim(uow.session, reg, 1)

    housekeeping.purge_succeeded_jobs(
        JobContext(job.id, job.kind, job.payload, job.meta, job.attempt, committing_db)
    )

    assert job_rows(committing_db, f"{label}.old-ok") == []
    assert len(job_rows(committing_db, f"{label}.new-ok")) == 1
    assert len(job_rows(committing_db, f"{label}.old-dead")) == 1


def test_recurring_job_is_enqueued_once_per_slot_by_several_workers(
    committing_db: Database, test_db_settings: DatabaseSettings
) -> None:
    reg = JobRegistry()
    kind = unique_kind("sweep")
    register(reg, kind, lambda ctx: None)
    recurring = [RecurringJob(kind, every=timedelta(hours=1))]

    with (
        running_worker(committing_db, test_db_settings, reg, recurring=recurring),
        running_worker(committing_db, test_db_settings, reg, recurring=recurring),
    ):
        wait_until(lambda: len(job_rows(committing_db, kind)) >= 1)
        time.sleep(1.5)

    rows = job_rows(committing_db, kind)
    assert len(rows) == 1
    assert rows[0].dedupe_key.startswith(f"{kind}:")


class FlakyDatabase:
    """Delegates to a real database but fails the first ``failures`` units of work opened by the
    worker's helper thread named ``thread_suffix`` (as a database restart would)."""

    def __init__(self, database: Database, thread_suffix: str, failures: int = 1) -> None:
        self._database = database
        self._thread_suffix = thread_suffix
        self.remaining = failures

    @contextmanager
    def unit_of_work(self) -> Iterator[Any]:
        if threading.current_thread().name.endswith(self._thread_suffix) and self.remaining > 0:
            self.remaining -= 1
            raise psycopg.OperationalError("connection refused (simulated database restart)")
        with self._database.unit_of_work() as uow:
            yield uow


def test_scheduler_survives_a_database_error(
    committing_db: Database, test_db_settings: DatabaseSettings
) -> None:
    reg = JobRegistry()
    kind = unique_kind("sweep-after-error")
    register(reg, kind, lambda ctx: None)
    flaky = FlakyDatabase(committing_db, "-scheduler")

    with running_worker(
        flaky,  # type: ignore[arg-type]
        test_db_settings,
        reg,
        recurring=[RecurringJob(kind, every=timedelta(hours=1))],
    ) as worker:
        wait_until(lambda: len(job_rows(committing_db, kind)) == 1)
        assert flaky.remaining == 0
        assert all(t.is_alive() for t in worker._threads)


def test_lease_renewer_survives_a_database_error(
    committing_db: Database, test_db_settings: DatabaseSettings
) -> None:
    reg = JobRegistry()
    kind = unique_kind("renew-after-error")
    runs = Counter[str]()

    def handler(ctx: JobContext) -> None:
        runs["calls"] += 1
        time.sleep(7)  # longer than the 6 s lease: only renewals keep it

    # Renewal is due at lease/3 (2 s) and, after the failure, retried a second later: the lease
    # still has about 2 s left, so only a renewer that stopped would let it lapse.
    register(reg, kind, handler, lease=timedelta(seconds=6))
    with committing_db.unit_of_work() as uow:
        enqueue(uow.session, kind, jobs_registry=reg)
    flaky = FlakyDatabase(committing_db, "-lease-renewer")

    # One worker: had its lease lapsed, its own main loop would reclaim the job and run it twice.
    with running_worker(flaky, test_db_settings, reg):  # type: ignore[arg-type]
        wait_until(lambda: job_rows(committing_db, kind)[0].status == "succeeded", timeout=20)

    assert flaky.remaining == 0
    assert runs["calls"] == 1
    assert job_rows(committing_db, kind)[0].attempts == 1


def test_watchdog_exits_when_the_loop_stalls(
    committing_db: Database, test_db_settings: DatabaseSettings
) -> None:
    exits: list[int] = []
    with running_worker(
        committing_db,
        test_db_settings,
        JobRegistry(),
        poll_interval=30,  # the loop sleeps far longer than the stall limit
        stall_timeout=0.5,
        exit_process=exits.append,
    ):
        wait_until(lambda: exits == [1], timeout=5)


def test_heartbeat_file_is_touched(
    committing_db: Database, test_db_settings: DatabaseSettings, tmp_path: Path
) -> None:
    heartbeat = tmp_path / "heartbeat"
    with running_worker(committing_db, test_db_settings, JobRegistry(), heartbeat_file=heartbeat):
        wait_until(heartbeat.exists)


def test_worker_refuses_to_start_on_an_unmigrated_database(
    test_db_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = f"signora_empty_{uuid.uuid4().hex[:8]}"
    admin = create_engine(
        test_db_settings.model_copy(update={"name": "postgres"}).url, isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    settings = load_settings()
    empty = settings.model_copy(update={"db": settings.db.model_copy(update={"name": name})})
    monkeypatch.setattr(worker_entrypoint, "get_settings", lambda: empty)
    monkeypatch.setattr(worker_entrypoint, "configure_logging", lambda *a, **k: None)
    try:
        assert worker_entrypoint.run_worker() == 1
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
