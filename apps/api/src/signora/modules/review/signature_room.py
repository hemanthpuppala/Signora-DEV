"""How much room a signature or initials place has above its line: an extension point.

Detection owns the rule (its ``signature_room``: the free space above a line, as it measures it
when it finds the field) and registers it, so review measures an approved version with exactly
that rule without depending on detection, which depends on review. Until something registers, a
place is drawn as its box is.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class MarkedPlace:
    """A signature or initials place: its id, page (from 1), box as displayed and kind (``blank``
    for a line found on the page; a form field's kind for the PDF's own field)."""

    id: uuid.UUID
    page: int
    rect: Box
    kind: str


# (the PDF, the places to measure, every place of the version by page) -> each place's top
SignatureRoom = Callable[
    [bytes, Sequence[MarkedPlace], Mapping[int, Sequence[Box]]], Mapping[uuid.UUID, float]
]

_rule: list[SignatureRoom] = []


def provide_signature_room(rule: SignatureRoom) -> None:
    """Register the rule (the same one again is a no-op; a second one replaces it)."""
    _rule[:] = [rule]


def signature_room(
    pdf: bytes, places: Sequence[MarkedPlace], others: Mapping[int, Sequence[Box]]
) -> dict[uuid.UUID, float] | None:
    """Each place's top by the registered rule; ``None`` when none is registered."""
    if not _rule or not places:
        return None
    return dict(_rule[0](pdf, places, others))
