"""The worker loop (backbone LLD §1.3-1.7, §7.4).

Threads inside one worker process:
- main loop: reclaims expired leases, claims due jobs up to the free slots, waits for a wake-up;
- job pool (``concurrency`` threads): runs handlers;
- listener: ``LISTEN`` on a dedicated connection, wakes the main loop when a job is committed;
- lease renewer: extends the lease of every running job every lease/3;
- scheduler: enqueues recurring sweeps once per time slot (deduplicated across workers);

Helper threads never die on an error (a database restart, an exhausted pool): they log it and
retry on their next tick, so a passing failure cannot silently stop lease renewal or the sweeps
while the main loop keeps the worker looking healthy.
- watchdog: exits the process if the main loop stops advancing, so the container restarts.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import psycopg

from signora.kernel.db import Database
from signora.kernel.jobs.core import (
    NOTIFY_CHANNEL,
    ClaimedJob,
    JobContext,
    JobRegistry,
    LeaseLostError,
    claim,
    enqueue,
    mark_failed,
    mark_succeeded,
    reclaim_expired,
    renew_lease,
)
from signora.kernel.logging import bind_context, clear_context, get_logger

log = get_logger("signora.worker")

DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_STALL_TIMEOUT = 60.0
HEARTBEAT_FILE_INTERVAL = 10.0
RECLAIM_INTERVAL = 1.0


@dataclass(frozen=True)
class RecurringJob:
    kind: str
    every: timedelta


@dataclass
class _Running:
    job: ClaimedJob
    lease: timedelta
    next_renewal: float


class Worker:
    def __init__(
        self,
        *,
        database: Database,
        conninfo: str,
        jobs_registry: JobRegistry,
        concurrency: int,
        recurring: Sequence[RecurringJob] = (),
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        stall_timeout: float = DEFAULT_STALL_TIMEOUT,
        heartbeat_file: Path | None = None,
        exit_process: Callable[[int], None] = os._exit,
    ) -> None:
        self.database = database
        self.conninfo = conninfo
        self.registry = jobs_registry
        self.concurrency = concurrency
        self.recurring = tuple(recurring)
        self.poll_interval = poll_interval
        self.stall_timeout = stall_timeout
        self.heartbeat_file = heartbeat_file
        self._exit_process = exit_process
        self.worker_id = f"worker-{uuid.uuid4().hex[:8]}"

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._running: dict[uuid.UUID, _Running] = {}
        self._lock = threading.Lock()
        self._last_beat = time.monotonic()
        self._last_heartbeat_file = 0.0
        self._threads: list[threading.Thread] = []

    # --- lifecycle ---------------------------------------------------------------------------

    def run(self) -> None:
        """Run until ``stop()``; returns after in-flight jobs finish."""
        log.info("worker.started", worker_id=self.worker_id, concurrency=self.concurrency)
        for target, name in (
            (self._listen, "listener"),
            (self._renew_leases, "lease-renewer"),
            (self._schedule, "scheduler"),
            (self._watchdog, "watchdog"),
        ):
            thread = threading.Thread(target=target, name=f"{self.worker_id}-{name}", daemon=True)
            thread.start()
            self._threads.append(thread)

        pool = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix=self.worker_id)
        last_reclaim = 0.0
        try:
            while not self._stop.is_set():
                self._beat()
                if time.monotonic() - last_reclaim >= RECLAIM_INTERVAL:
                    self._reclaim()
                    last_reclaim = time.monotonic()
                for job in self._claim_free_slots():
                    pool.submit(self._execute, job)
                self._wake.wait(timeout=self.poll_interval)
                self._wake.clear()
        finally:
            pool.shutdown(wait=True)
            for thread in self._threads:
                thread.join(timeout=5)
            log.info("worker.stopped", worker_id=self.worker_id)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # --- main loop pieces --------------------------------------------------------------------

    def _beat(self) -> None:
        self._last_beat = time.monotonic()
        if self.heartbeat_file and time.monotonic() - self._last_heartbeat_file >= (
            HEARTBEAT_FILE_INTERVAL
        ):
            self.heartbeat_file.touch()
            self._last_heartbeat_file = time.monotonic()

    def _reclaim(self) -> None:
        with self.database.unit_of_work() as uow:
            requeued, dead = reclaim_expired(uow.session, self.registry)
        if requeued or dead:
            log.warning("jobs.reclaimed", requeued=requeued, dead=dead)

    def _claim_free_slots(self) -> list[ClaimedJob]:
        with self._lock:
            free = self.concurrency - len(self._running)
        if free <= 0:
            return []
        with self.database.unit_of_work() as uow:
            jobs = claim(uow.session, self.registry, free)
        now = time.monotonic()
        with self._lock:
            for job in jobs:
                lease = self.registry.get(job.kind).lease
                self._running[job.id] = _Running(job, lease, now + lease.total_seconds() / 3)
        return jobs

    def _execute(self, job: ClaimedJob) -> None:
        kind = self.registry.get(job.kind)
        clear_context()
        bind_context(job_id=str(job.id), job_kind=job.kind, attempt=job.attempt)
        if job.meta.get("request_id"):
            bind_context(request_id=job.meta["request_id"])
        context = JobContext(job.id, job.kind, job.payload, job.meta, job.attempt, self.database)
        started = time.monotonic()
        try:
            kind.handler(context)
            if not context.completed:
                with self.database.unit_of_work() as uow:
                    if not mark_succeeded(uow.session, job.id, job.attempt):
                        raise LeaseLostError(f"job {job.id} attempt {job.attempt} lost its lease")
            log.info("job.succeeded", duration_ms=round((time.monotonic() - started) * 1000, 1))
        except LeaseLostError:
            log.warning("job.lease_lost")
        except Exception as error:
            log.exception("job.failed")
            with self.database.unit_of_work() as uow:
                status = mark_failed(uow.session, job, kind, error)
            if status == "dead":
                log.error("job.dead", max_attempts=kind.max_attempts)
        finally:
            with self._lock:
                self._running.pop(job.id, None)
            clear_context()
            self._wake.set()

    # --- helper threads ----------------------------------------------------------------------

    def _listen(self) -> None:
        while not self._stop.is_set():
            try:
                with psycopg.connect(self.conninfo, autocommit=True) as connection:
                    connection.execute(f"LISTEN {NOTIFY_CHANNEL}")
                    while not self._stop.is_set():
                        for _ in connection.notifies(timeout=1.0, stop_after=1):
                            self._wake.set()
            except psycopg.Error:
                log.exception("worker.listener_error")
                self._stop.wait(timeout=2.0)

    def _renew_leases(self) -> None:
        while not self._stop.wait(timeout=1.0):
            now = time.monotonic()
            with self._lock:
                due = [r for r in self._running.values() if r.next_renewal <= now]
            for running in due:
                try:
                    with self.database.unit_of_work() as uow:
                        renewed = renew_lease(uow.session, running.job, running.lease)
                except Exception:
                    # next_renewal is unchanged, so this job is retried on the next tick (1 s).
                    log.exception("worker.lease_renewal_error", job_id=str(running.job.id))
                    continue
                running.next_renewal = now + running.lease.total_seconds() / 3
                if not renewed:
                    log.warning("job.lease_renewal_lost", job_id=str(running.job.id))

    def _schedule(self) -> None:
        last_slot: dict[str, int] = {}
        while not self._stop.is_set():
            now = time.time()
            for job in self.recurring:
                slot = int(now // job.every.total_seconds())
                if last_slot.get(job.kind) == slot:
                    continue
                try:
                    with self.database.unit_of_work() as uow:
                        enqueue(
                            uow.session,
                            job.kind,
                            dedupe_key=f"{job.kind}:{slot}",
                            jobs_registry=self.registry,
                        )
                except Exception:
                    # The slot is not recorded, so it is retried on the next tick (1 s).
                    log.exception("worker.schedule_error", job_kind=job.kind)
                    continue
                last_slot[job.kind] = slot
            self._stop.wait(timeout=1.0)

    def _watchdog(self) -> None:
        while not self._stop.wait(timeout=min(5.0, self.stall_timeout / 4)):
            stalled_for = time.monotonic() - self._last_beat
            if stalled_for > self.stall_timeout:
                log.critical("worker.stalled", stalled_seconds=round(stalled_for, 1))
                self._exit_process(1)
                return
