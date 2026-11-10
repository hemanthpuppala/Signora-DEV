"""The size of the agreement's text beside each place (Phase 7b LLD), read from the PDF once, when
its version is approved. Pure: bytes in, sizes out.

A place takes the median size of the words on its row (their vertical centres within the place's
height, widened a little); with none on its row, the page's median. Rounded to half a point, so a
document's one body size reads as one size. Only text someone can read counts: words smaller than
the smallest size a value is drawn at (a scan's hidden text layer, a hairline of fine print) are
not the agreement's text, and would have values drawn unreadably small.
"""

from __future__ import annotations

import uuid
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

import pymupdf

from signora.modules.typesetting.fit import MIN_SIZE
from signora.modules.typesetting.mupdf import MUPDF_LOCK

ROW_SLACK = 2.0  # points: a word whose centre is this close above or below the box is on its row
# The words and their sizes only: a page's images are never decoded for it.
_TEXT_ONLY = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES


@dataclass(frozen=True)
class Measured:
    """A place to measure: its id, page (from 1) and box as displayed, in PDF points."""

    id: uuid.UUID
    page: int
    rect: tuple[float, float, float, float]


def _half(size: float) -> float:
    return round(size * 2) / 2


def text_sizes(pdf: bytes, places: Sequence[Measured]) -> dict[uuid.UUID, float]:
    """O(W log W + P log W) per page, for W words and P places: the words sorted by centre, each
    place's row found by binary search."""
    by_page: dict[int, list[Measured]] = defaultdict(list)
    for place in places:
        by_page[place.page].append(place)
    sizes: dict[uuid.UUID, float] = {}
    with MUPDF_LOCK, pymupdf.open(stream=pdf, filetype="pdf") as document:
        for number, wanted in by_page.items():
            if not 1 <= number <= document.page_count:
                continue
            page = document.load_page(number - 1)
            words: list[tuple[float, float]] = []  # (centre y as displayed, size)
            for block in page.get_text("dict", flags=_TEXT_ONLY)["blocks"]:
                for line in block.get("lines", ()):
                    for span in line["spans"]:
                        if not span["text"].strip() or span["size"] < MIN_SIZE:
                            continue
                        shown = pymupdf.Rect(span["bbox"]) * page.rotation_matrix
                        words.append(((shown.y0 + shown.y1) / 2, float(span["size"])))
            if not words:
                continue
            words.sort()
            centres = [centre for centre, _ in words]
            page_size = _half(median(size for _, size in words))
            for place in wanted:
                _, y0, _, y1 = place.rect
                lo = bisect_left(centres, y0 - ROW_SLACK)
                hi = bisect_right(centres, y1 + ROW_SLACK)
                row = [size for _, size in words[lo:hi]]
                sizes[place.id] = min(72.0, _half(median(row)) if row else page_size)
    return sizes
