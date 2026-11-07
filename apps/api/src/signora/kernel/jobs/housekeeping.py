"""Housekeeping sweep for the jobs table (backbone LLD §1.2, topic 2 retention)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from signora.kernel.jobs.core import JobContext, JobKind, JobRegistry
from signora.kernel.jobs.worker import RecurringJob

HOUSEKEEPING = "sweep.housekeeping"
SUCCEEDED_RETENTION = timedelta(days=7)


def purge_succeeded_jobs(context: JobContext) -> None:
    """Delete succeeded jobs older than the retention period. Dead jobs are kept for diagnosis."""
    with context.complete() as uow:
        uow.session.execute(
            text(
                """
                DELETE FROM jobs
                WHERE status = 'succeeded'
                  AND finished_at < now() - make_interval(secs => :retention)
                """
            ),
            {"retention": SUCCEEDED_RETENTION.total_seconds()},
        )


def register(jobs_registry: JobRegistry) -> RecurringJob:
    jobs_registry.register(
        JobKind(HOUSEKEEPING, purge_succeeded_jobs, max_attempts=3, lease=timedelta(minutes=2))
    )
    return RecurringJob(HOUSEKEEPING, every=timedelta(hours=1))
