"""How many sends a department has, from the module that sends (Phase 7 LLD §6).

An extension point: envelopes registers how it counts, so departments shows real numbers without
depending on envelopes (the dependency stays one-way, as with identity's member-removal hooks).
Until something registers, every count is zero.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SendCounts:
    sent: int = 0  # every send that was not withdrawn
    signed: int = 0  # completed: everyone signed
    pending: int = 0  # still in progress


SendCountsProvider = Callable[
    [Session, uuid.UUID, Sequence[uuid.UUID]], Mapping[uuid.UUID, SendCounts]
]

_providers: list[SendCountsProvider] = []


def provide_send_counts(provider: SendCountsProvider) -> None:
    """Register how sends are counted; registering the same function again is a no-op."""
    if provider not in _providers:
        _providers.append(provider)


def send_counts(
    session: Session, workspace_id: uuid.UUID, department_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, SendCounts]:
    """Each department's counts, zero where nothing was sent (one query per provider)."""
    counts = {department_id: SendCounts() for department_id in department_ids}
    for provider in _providers:
        for department_id, found in provider(session, workspace_id, department_ids).items():
            counts[department_id] = found
    return counts
