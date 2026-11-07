"""Retention sweep for idempotency records (backbone LLD §3.3: 24 hours)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from signora.kernel.jobs import JobContext, JobKind, JobRegistry, RecurringJob

SWEEP = "sweep.idempotency_keys"
RETENTION = timedelta(hours=24)


def purge_expired_keys(context: JobContext) -> None:
    with context.complete() as uow:
        uow.session.execute(
            text(
                "DELETE FROM idempotency_keys"
                " WHERE created_at < now() - make_interval(secs => :retention)"
            ),
            {"retention": RETENTION.total_seconds()},
        )


def register(jobs_registry: JobRegistry) -> RecurringJob:
    jobs_registry.register(
        JobKind(SWEEP, purge_expired_keys, max_attempts=3, lease=timedelta(minutes=2))
    )
    return RecurringJob(SWEEP, every=timedelta(hours=1))
