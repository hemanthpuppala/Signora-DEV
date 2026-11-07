"""Background work of the identity module: the retention sweep (Phase 2 LLD §4.1, §8.3)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from signora.kernel.config import get_settings
from signora.kernel.jobs import JobContext, JobKind, JobRegistry, RecurringJob
from signora.modules.identity_access.sessions import purge_idle_sessions

SWEEP = "sweep.identity"
TOKEN_RETENTION = timedelta(days=7)


def sweep(context: JobContext) -> None:
    """Delete idle sessions, and link tokens a week after they expired."""
    idle = timedelta(hours=get_settings().auth.session_idle_hours)
    with context.complete() as uow:
        purge_idle_sessions(uow.session, idle)
        uow.session.execute(
            text(
                "DELETE FROM email_tokens WHERE expires_at < now() - make_interval(secs => :keep)"
            ),
            {"keep": TOKEN_RETENTION.total_seconds()},
        )


def register(jobs_registry: JobRegistry) -> list[RecurringJob]:
    jobs_registry.register(JobKind(SWEEP, sweep, max_attempts=3, lease=timedelta(minutes=2)))
    return [RecurringJob(SWEEP, every=timedelta(hours=1))]
