"""How many templates wait for approval in a department, from the module that holds them.

An extension point like the send counts (``sends``): documents registers how it counts, so a
department shows a dot for templates waiting without depending on documents. Until something
registers, every count is zero.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence

from sqlalchemy.orm import Session

ApprovalCountsProvider = Callable[
    [Session, uuid.UUID, Sequence[uuid.UUID]], Mapping[uuid.UUID, int]
]

_providers: list[ApprovalCountsProvider] = []


def provide_approval_counts(provider: ApprovalCountsProvider) -> None:
    """Register how templates waiting for approval are counted (the same function again: no-op)."""
    if provider not in _providers:
        _providers.append(provider)


def approval_counts(
    session: Session, workspace_id: uuid.UUID, department_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Each department's templates waiting for approval, zero where none; one query a provider."""
    counts = dict.fromkeys(department_ids, 0)
    for provider in _providers:
        for department_id, found in provider(session, workspace_id, department_ids).items():
            counts[department_id] = found
    return counts
