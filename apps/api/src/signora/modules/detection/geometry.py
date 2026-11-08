"""Boxes on a page and a row index over them (Phase 5 LLD topic 2).

Boxes are ``(x0, y0, x1, y1)`` in PDF points, origin top-left. A ``RowIndex`` buckets items by the
rows of the page they span, so finding what sits near a box looks at its neighbours only: O(1)
buckets per lookup instead of every item on the page.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

Box = tuple[float, float, float, float]

BUCKET = 12.0  # points per bucket: about one line of text


def center(box: Box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def inside(point: tuple[float, float], box: Box) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def same_row(a: Box, b: Box) -> bool:
    """The two boxes overlap vertically by at least half of the shorter one."""
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    return overlap >= 0.5 * min(a[3] - a[1], b[3] - b[1])


def overlaps_horizontally(a: Box, b: Box) -> bool:
    return min(a[2], b[2]) - max(a[0], b[0]) > 0


def union(boxes: Iterable[Box]) -> Box:
    items = list(boxes)
    return (
        min(b[0] for b in items),
        min(b[1] for b in items),
        max(b[2] for b in items),
        max(b[3] for b in items),
    )


def cut(text: str | None, limit: int) -> str | None:
    """``None`` for empty text; text longer than ``limit`` ends with an ellipsis."""
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


class RowIndex[T]:
    """Items with a box, bucketed by the rows they span."""

    def __init__(self, items: Iterable[tuple[Box, T]]) -> None:
        self._buckets: dict[int, list[tuple[Box, T]]] = {}
        for box, item in items:
            entry = (box, item)  # one object in every bucket it spans, so ``near`` yields it once
            for bucket in range(int(box[1] // BUCKET), int(box[3] // BUCKET) + 1):
                self._buckets.setdefault(bucket, []).append(entry)

    def near(self, top: float, bottom: float) -> Iterator[tuple[Box, T]]:
        """Each item spanning a row between ``top`` and ``bottom``, once."""
        seen: set[int] = set()
        for bucket in range(int(top // BUCKET), int(bottom // BUCKET) + 1):
            for entry in self._buckets.get(bucket, ()):
                if id(entry) not in seen:
                    seen.add(id(entry))
                    yield entry

    def holding(self, point: tuple[float, float]) -> Iterator[tuple[Box, T]]:
        """Each item whose box holds the point."""
        for box, item in self._buckets.get(int(point[1] // BUCKET), ()):
            if inside(point, box):
                yield box, item
