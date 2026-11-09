"""How close the AI came, measured when a version is approved (Phase 6 LLD §1.5, §11; platform
§7.6). Pure: no database.

A proposed place and an approved place match when they are on the same page, of the same family
(signing, a mark, or data) and overlap with IoU >= 0.5; matching is one to one, greedy by
descending IoU. Candidates come from a sweep over each page's places sorted by their left edge, so
only boxes that overlap horizontally are compared: O(P log P + C log C) for P places and C
candidate pairs, not O(P^2).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from signora.modules.review.values import family

THRESHOLD = 0.5

Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class BaselinePlace:
    """One place of the AI's proposal as review keeps it (``version_reviews.proposal``)."""

    page: int
    rect: Rect
    holds: str
    label: str
    filled_by: str
    party_id: uuid.UUID | None

    def as_json(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "rect": list(self.rect),
            "holds": self.holds,
            "label": self.label,
            "filled_by": self.filled_by,
            "party_id": str(self.party_id) if self.party_id else None,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> BaselinePlace:
        x0, y0, x1, y1 = (float(v) for v in data["rect"])
        party = data.get("party_id")
        return cls(
            page=int(data["page"]),
            rect=(x0, y0, x1, y1),
            holds=str(data["holds"]),
            label=str(data["label"]),
            filled_by=str(data["filled_by"]),
            party_id=uuid.UUID(party) if party else None,
        )

    def moved(self, party_ids: Mapping[uuid.UUID, uuid.UUID]) -> BaselinePlace:
        """The same place with its party under a version made by editing's ids; a party the
        source no longer had stays unknown, so a field given to it counts as reassigned."""
        if self.party_id is None:
            return self
        return replace(self, party_id=party_ids.get(self.party_id))


@dataclass(frozen=True)
class ApprovedPlace:
    field_id: uuid.UUID
    page: int
    rect: Rect
    holds: str
    label: str
    filled_by: str
    party_id: uuid.UUID | None


@dataclass(frozen=True)
class Metrics:
    true_positives: int  # matched places
    false_positives: int  # proposed, not approved
    false_negatives: int  # approved, not proposed (added by hand)
    precision: float | None  # None when there is nothing to divide by
    recall: float | None
    f1: float | None
    relabelled: int  # matched fields whose label changed
    retyped: int  # … whose type changed
    reassigned: int  # … whose filler changed
    mean_iou: float | None


def iou(a: Rect, b: Rect) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    overlap = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return overlap / union if union > 0 else 0.0


def match(
    proposed: Sequence[BaselinePlace], approved: Sequence[ApprovedPlace]
) -> list[tuple[int, int, float]]:
    """One-to-one pairs ``(proposed index, approved index, IoU)``, greedy by descending IoU."""
    pages: dict[int, tuple[list[int], list[int]]] = {}
    for i, ours_place in enumerate(proposed):
        pages.setdefault(ours_place.page, ([], []))[0].append(i)
    for j, their_place in enumerate(approved):
        pages.setdefault(their_place.page, ([], []))[1].append(j)

    candidates: list[tuple[float, int, int]] = []
    for ours, theirs in pages.values():
        events = sorted(
            [(proposed[i].rect[0], 0, i) for i in ours]
            + [(approved[j].rect[0], 1, j) for j in theirs]
        )
        open_proposed: list[int] = []
        open_approved: list[int] = []
        for left, side, index in events:
            # Boxes that ended before this one starts can overlap nothing still to come.
            open_proposed = [i for i in open_proposed if proposed[i].rect[2] > left]
            open_approved = [j for j in open_approved if approved[j].rect[2] > left]
            if side == 0:
                place_p = proposed[index]
                for j in open_approved:
                    if family(approved[j].holds) == family(place_p.holds):
                        score = iou(place_p.rect, approved[j].rect)
                        if score >= THRESHOLD:
                            candidates.append((score, index, j))
                open_proposed.append(index)
            else:
                place_a = approved[index]
                for i in open_proposed:
                    if family(proposed[i].holds) == family(place_a.holds):
                        score = iou(proposed[i].rect, place_a.rect)
                        if score >= THRESHOLD:
                            candidates.append((score, i, index))
                open_approved.append(index)

    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    used_p: set[int] = set()
    used_a: set[int] = set()
    pairs: list[tuple[int, int, float]] = []
    for score, i, j in candidates:
        if i not in used_p and j not in used_a:
            used_p.add(i)
            used_a.add(j)
            pairs.append((i, j, score))
    return pairs


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def measure(proposed: Sequence[BaselinePlace], approved: Sequence[ApprovedPlace]) -> Metrics:
    """Place-level precision, recall and F1, and, for each approved field with a matched place,
    whether its label, type or filler differs from the proposed field of its best-matched place."""
    pairs = match(proposed, approved)
    tp = len(pairs)
    precision = _ratio(tp, len(proposed))
    recall = _ratio(tp, len(approved))
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else (0.0 if precision is not None and recall is not None else None)
    )
    best: dict[uuid.UUID, tuple[float, BaselinePlace, ApprovedPlace]] = {}
    for i, j, score in pairs:
        field_id = approved[j].field_id
        if field_id not in best or score > best[field_id][0]:
            best[field_id] = (score, proposed[i], approved[j])
    relabelled = retyped = reassigned = 0
    for _, was, now in best.values():
        relabelled += was.label.strip().casefold() != now.label.strip().casefold()
        retyped += was.holds != now.holds
        reassigned += (was.filled_by, was.party_id) != (now.filled_by, now.party_id)
    return Metrics(
        true_positives=tp,
        false_positives=len(proposed) - tp,
        false_negatives=len(approved) - tp,
        precision=precision,
        recall=recall,
        f1=f1,
        relabelled=relabelled,
        retyped=retyped,
        reassigned=reassigned,
        mean_iou=sum(score for _, _, score in pairs) / tp if tp else None,
    )
