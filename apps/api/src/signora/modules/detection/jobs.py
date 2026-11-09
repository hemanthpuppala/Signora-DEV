"""Detection's background work (Phase 5 LLD §1.2-1.3).

The run that follows processing is the ``DocumentVersionProcessed`` subscriber itself (no second
hop); a run started by hand is a ``detection.run`` job. Both run ``run.run_detection`` and settle a
dead job the same way, so a version never stays "Finding fields".
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from functools import cache

from signora.kernel.blobstore import BlobStore, blob_store_from_settings
from signora.kernel.config import get_settings
from signora.kernel.events import bus
from signora.kernel.jobs import JobContext, JobKind, JobRegistry, RecurringJob
from signora.modules.detection.ai import Assigner, OpenAIAssigner
from signora.modules.detection.run import run_detection, settle_dead_run
from signora.modules.documents import DocumentVersionProcessed

RUN = "detection.run"
SUBSCRIBER = "detection"
MAX_ATTEMPTS = 5  # with backbone §1.4's backoff: 30 s doubling, about 8 minutes in all
LEASE = timedelta(minutes=10)  # renewed while it runs; one AI call may take AI_TIMEOUT_SECONDS


@cache
def _dependencies() -> tuple[BlobStore, Assigner]:
    """Built once per process: settings do not change while it runs."""
    settings = get_settings()
    return blob_store_from_settings(settings.blob_store), OpenAIAssigner(settings.ai)


@bus.subscribe(
    DocumentVersionProcessed,
    SUBSCRIBER,
    max_attempts=MAX_ATTEMPTS,
    lease=LEASE,
    on_dead=settle_dead_run,
)
def after_processing(context: JobContext, event: DocumentVersionProcessed) -> None:
    store, assigner = _dependencies()
    run_detection(context, event.version_id, run_id=None, store=store, assigner=assigner)


def run_by_hand(context: JobContext) -> None:
    store, assigner = _dependencies()
    run_detection(
        context,
        uuid.UUID(context.payload["version_id"]),
        run_id=uuid.UUID(context.payload["run_id"]),
        store=store,
        assigner=assigner,
    )


def register(jobs_registry: JobRegistry) -> list[RecurringJob]:
    """``detection.run``; the subscriber registers itself with the event bus on import."""
    jobs_registry.register(
        JobKind(RUN, run_by_hand, max_attempts=MAX_ATTEMPTS, lease=LEASE, on_dead=settle_dead_run)
    )
    return []
