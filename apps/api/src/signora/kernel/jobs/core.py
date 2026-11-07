"""Job queue primitives (backbone LLD topics 1-2).

All state transitions are single SQL statements guarded by the claimed attempt number, so a worker
that lost its lease can never mark a job succeeded or failed (LLD §1.4).
"""

from __future__ import annotations

import json
import random
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import Result, text
from sqlalchemy.orm import Session

from signora.kernel.db import Database, UnitOfWork
from signora.kernel.logging import current_context

NOTIFY_CHANNEL = "signora_jobs"
BACKOFF_BASE_SECONDS = 30.0
BACKOFF_CAP_SECONDS = 3600.0
BACKOFF_JITTER = 0.2
LAST_ERROR_MAX = 2000

JsonDict = dict[str, Any]
Handler = Callable[["JobContext"], None]


class UnknownJobKindError(LookupError):
    pass


class LeaseLostError(RuntimeError):
    """The job was reclaimed by another worker; this worker's result must be discarded."""


@dataclass(frozen=True)
class JobKind:
    name: str
    handler: Handler
    max_attempts: int
    lease: timedelta

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.lease <= timedelta(0):
            raise ValueError("lease must be positive")


@dataclass
class JobRegistry:
    """The single source of job kinds and their retry policy (LLD §1.4)."""

    _kinds: dict[str, JobKind] = field(default_factory=dict)

    def register(self, kind: JobKind) -> JobKind:
        existing = self._kinds.get(kind.name)
        if existing is not None and existing != kind:
            raise ValueError(f"job kind {kind.name!r} is already registered")
        self._kinds[kind.name] = kind
        return kind

    def get(self, name: str) -> JobKind:
        try:
            return self._kinds[name]
        except KeyError:
            raise UnknownJobKindError(name) from None

    def __contains__(self, name: object) -> bool:
        return name in self._kinds

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._kinds)


registry = JobRegistry()
"""Application-wide registry; modules register their job kinds in their ``handlers`` module."""


def _affected(result: Result[Any]) -> int:
    """Rows changed by an UPDATE/DELETE (``rowcount`` exists only on cursor results)."""
    return int(getattr(result, "rowcount", 0))


def backoff_seconds(attempt: int) -> float:
    """Delay before the next try: 30 s doubling per attempt, capped at 1 h, ±20 % jitter."""
    base = min(BACKOFF_BASE_SECONDS * 2 ** max(attempt - 1, 0), BACKOFF_CAP_SECONDS)
    jitter = random.uniform(1 - BACKOFF_JITTER, 1 + BACKOFF_JITTER)  # noqa: S311 - not crypto
    return float(base * jitter)


def enqueue(
    session: Session,
    kind: str,
    payload: Mapping[str, Any] | None = None,
    *,
    run_after: timedelta | None = None,
    dedupe_key: str | None = None,
    meta: Mapping[str, Any] | None = None,
    jobs_registry: JobRegistry = registry,
) -> bool:
    """Queue a job inside the caller's transaction. Returns False when deduplicated.

    The job (and its wake-up notification) become visible only when the caller commits.
    """
    if kind not in jobs_registry:
        raise UnknownJobKindError(kind)
    job_meta: JsonDict = dict(meta or {})
    request_id = current_context().get("request_id")
    if request_id and "request_id" not in job_meta:
        job_meta["request_id"] = request_id
    inserted = session.execute(
        text(
            """
            INSERT INTO jobs (kind, payload, meta, dedupe_key, run_at)
            VALUES (:kind, CAST(:payload AS jsonb), CAST(:meta AS jsonb), :dedupe_key,
                    now() + make_interval(secs => :delay))
            ON CONFLICT (dedupe_key) DO NOTHING
            RETURNING id
            """
        ),
        {
            "kind": kind,
            "payload": json.dumps(dict(payload or {})),
            "meta": json.dumps(job_meta),
            "dedupe_key": dedupe_key,
            "delay": run_after.total_seconds() if run_after else 0.0,
        },
    ).scalar_one_or_none()
    if inserted is None:
        return False
    session.execute(
        text("SELECT pg_notify(:channel, :kind)"), {"channel": NOTIFY_CHANNEL, "kind": kind}
    )
    return True


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    kind: str
    payload: JsonDict
    meta: JsonDict
    attempt: int


def claim(session: Session, jobs_registry: JobRegistry, limit: int) -> list[ClaimedJob]:
    """Claim up to ``limit`` due jobs of registered kinds; two workers never get the same job."""
    if limit <= 0 or not jobs_registry.names:
        return []
    leases = {name: jobs_registry.get(name).lease.total_seconds() for name in jobs_registry.names}
    rows = session.execute(
        text(
            """
            WITH picked AS (
                SELECT id FROM jobs
                WHERE status = 'queued' AND run_at <= now() AND kind = ANY(:kinds)
                ORDER BY run_at
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            UPDATE jobs AS j
            SET status = 'running',
                attempts = j.attempts + 1,
                lease_expires_at = now()
                    + make_interval(secs => (CAST(:leases AS jsonb) ->> j.kind)::float8)
            FROM picked
            WHERE j.id = picked.id
            RETURNING j.id, j.kind, j.payload, j.meta, j.attempts
            """
        ),
        {"kinds": list(jobs_registry.names), "limit": limit, "leases": json.dumps(leases)},
    ).all()
    return [ClaimedJob(r.id, r.kind, r.payload, r.meta, r.attempts) for r in rows]


def mark_succeeded(session: Session, job_id: uuid.UUID, attempt: int) -> bool:
    """Guarded success mark; False when the claim is no longer current."""
    result = session.execute(
        text(
            """
            UPDATE jobs SET status = 'succeeded', finished_at = now(), lease_expires_at = NULL
            WHERE id = :id AND status = 'running' AND attempts = :attempt
            """
        ),
        {"id": job_id, "attempt": attempt},
    )
    return _affected(result) == 1


def mark_failed(
    session: Session, job: ClaimedJob, kind: JobKind, error: BaseException
) -> str | None:
    """Record a failed attempt: re-queue with backoff, or ``dead`` after the last attempt.

    Returns the new status, or None when the claim was no longer current.
    """
    dead = job.attempt >= kind.max_attempts
    message = f"{type(error).__name__}: {error}"[:LAST_ERROR_MAX]
    result = session.execute(
        text(
            """
            UPDATE jobs
            SET status = :status,
                last_error = :error,
                lease_expires_at = NULL,
                run_at = now() + make_interval(secs => :delay),
                finished_at = CASE WHEN :dead THEN now() ELSE NULL END
            WHERE id = :id AND status = 'running' AND attempts = :attempt
            """
        ),
        {
            "status": "dead" if dead else "queued",
            "error": message,
            "delay": 0.0 if dead else backoff_seconds(job.attempt),
            "dead": dead,
            "id": job.id,
            "attempt": job.attempt,
        },
    )
    if _affected(result) != 1:
        return None
    return "dead" if dead else "queued"


def renew_lease(session: Session, job: ClaimedJob, lease: timedelta) -> bool:
    result = session.execute(
        text(
            """
            UPDATE jobs SET lease_expires_at = now() + make_interval(secs => :lease)
            WHERE id = :id AND status = 'running' AND attempts = :attempt
            """
        ),
        {"lease": lease.total_seconds(), "id": job.id, "attempt": job.attempt},
    )
    return _affected(result) == 1


def reclaim_expired(session: Session, jobs_registry: JobRegistry) -> tuple[int, int]:
    """Return expired running jobs to the queue (or ``dead`` if out of attempts).

    A reclaimed claim already counted as an attempt. Returns (requeued, dead).
    """
    max_attempts = {n: jobs_registry.get(n).max_attempts for n in jobs_registry.names}
    rows = session.execute(
        text(
            """
            WITH expired AS (
                SELECT id FROM jobs
                WHERE status = 'running' AND lease_expires_at < now() AND kind = ANY(:kinds)
                FOR UPDATE SKIP LOCKED
            )
            UPDATE jobs AS j
            SET status = CASE
                    WHEN j.attempts >= (CAST(:max_attempts AS jsonb) ->> j.kind)::int THEN 'dead'
                    ELSE 'queued' END,
                last_error = 'lease expired (worker stopped or stalled)',
                lease_expires_at = NULL,
                run_at = now(),
                finished_at = CASE
                    WHEN j.attempts >= (CAST(:max_attempts AS jsonb) ->> j.kind)::int THEN now()
                    ELSE NULL END
            FROM expired
            WHERE j.id = expired.id
            RETURNING j.status
            """
        ),
        {"kinds": list(jobs_registry.names), "max_attempts": json.dumps(max_attempts)},
    ).scalars()
    statuses = list(rows)
    return statuses.count("queued"), statuses.count("dead")


@dataclass(frozen=True)
class JobContext:
    """What a handler receives (LLD §1.8). Handlers open short units of work themselves."""

    job_id: uuid.UUID
    kind: str
    payload: JsonDict
    meta: JsonDict
    attempt: int
    database: Database
    _state: dict[str, bool] = field(default_factory=lambda: {"completed": False})

    @contextmanager
    def unit_of_work(self) -> Iterator[UnitOfWork]:
        """A short transaction for reads or intermediate writes. Never hold it across slow I/O."""
        with self.database.unit_of_work() as uow:
            yield uow

    @contextmanager
    def complete(self) -> Iterator[UnitOfWork]:
        """Final writes plus the guarded success mark, committed together.

        Raises ``LeaseLostError`` (rolling everything back) when another worker now owns the job.
        """
        with self.database.unit_of_work() as uow:
            yield uow
            if not mark_succeeded(uow.session, self.job_id, self.attempt):
                raise LeaseLostError(f"job {self.job_id} attempt {self.attempt} lost its lease")
            self._state["completed"] = True

    @property
    def completed(self) -> bool:
        return self._state["completed"]
