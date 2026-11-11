"""Background work of the signing module (Phase 8 LLD §12)."""

from __future__ import annotations

from signora.kernel.jobs import JobRegistry, RecurringJob
from signora.modules.signing import completion


def register(jobs_registry: JobRegistry) -> list[RecurringJob]:
    completion.register(jobs_registry)
    return []
