"""Background work of the documents module (Phase 4 LLD)."""

from __future__ import annotations

from datetime import timedelta

from signora.kernel.jobs import JobKind, JobRegistry, RecurringJob
from signora.modules.documents import uploads


def register(jobs_registry: JobRegistry) -> list[RecurringJob]:
    jobs_registry.register(
        JobKind(uploads.SWEEP, uploads.sweep, max_attempts=3, lease=timedelta(minutes=2))
    )
    return [RecurringJob(uploads.SWEEP, every=timedelta(hours=1))]
