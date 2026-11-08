"""Background work of the documents module (Phase 4 LLD)."""

from __future__ import annotations

from datetime import timedelta

from signora.kernel.blobstore import blob_store_from_settings
from signora.kernel.config import get_settings
from signora.kernel.jobs import JobContext, JobKind, JobRegistry, RecurringJob
from signora.modules.documents import processing, uploads


def process_version(context: JobContext) -> None:
    settings = get_settings()
    processing.process_version(
        context,
        store=blob_store_from_settings(settings.blob_store),
        gotenberg_url=settings.gotenberg.base_url,
        max_pages=settings.documents.max_pages,
    )


def register(jobs_registry: JobRegistry) -> list[RecurringJob]:
    jobs_registry.register(
        JobKind(uploads.SWEEP, uploads.sweep, max_attempts=3, lease=timedelta(minutes=2))
    )
    jobs_registry.register(
        JobKind(
            processing.PROCESS,
            process_version,
            max_attempts=processing.MAX_ATTEMPTS,
            lease=processing.LEASE,
        )
    )
    return [RecurringJob(uploads.SWEEP, every=timedelta(hours=1))]
