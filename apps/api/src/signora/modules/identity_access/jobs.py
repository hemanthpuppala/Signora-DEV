"""Background work of the identity module: link emails and the retention sweep (Phase 2 LLD)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from signora.kernel.config import get_settings
from signora.kernel.jobs import JobContext, JobKind, JobRegistry, RecurringJob
from signora.modules.identity_access import signup
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


def signup_request(context: JobContext) -> None:
    settings = get_settings()
    signup.handle_signup_request(
        context, base_url=str(settings.app.public_base_url), settings=settings.auth
    )


def register(jobs_registry: JobRegistry) -> list[RecurringJob]:
    lease = timedelta(minutes=2)
    jobs_registry.register(JobKind(SWEEP, sweep, max_attempts=3, lease=lease))
    jobs_registry.register(
        JobKind(signup.SIGNUP_REQUEST, signup_request, max_attempts=8, lease=lease)
    )
    return [RecurringJob(SWEEP, every=timedelta(hours=1))]
