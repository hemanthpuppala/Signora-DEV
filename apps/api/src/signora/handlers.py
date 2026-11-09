"""Registry of background job kinds and recurring sweeps.

Both the API (which enqueues) and the worker (which runs) call ``register_all`` so they agree on
the job kinds. Add each module's ``handlers.register`` here as modules arrive.
"""

from __future__ import annotations

from signora.kernel.idempotency import housekeeping as idempotency_housekeeping
from signora.kernel.jobs import JobRegistry, RecurringJob, housekeeping
from signora.modules.detection import jobs as detection_jobs
from signora.modules.documents import jobs as documents_jobs
from signora.modules.identity_access import jobs as identity_jobs
from signora.modules.notifications import service as notifications


def register_all(jobs_registry: JobRegistry) -> list[RecurringJob]:
    """Register every job kind; returns the recurring sweeps the worker schedules."""
    return [
        housekeeping.register(jobs_registry),
        idempotency_housekeeping.register(jobs_registry),
        notifications.register(jobs_registry),
        *identity_jobs.register(jobs_registry),
        *documents_jobs.register(jobs_registry),
        *detection_jobs.register(jobs_registry),
    ]
