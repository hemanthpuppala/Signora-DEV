"""Where a signature or initials is drawn: its place, grown upwards from its line to a readable
height, but never over the agreement's own text above it. One rule for the signed PDF and for the
signer's screen (both read ``mark_top``).

The room above a place is read from the PDF once, when its version is approved (``mark_tops``):
the lowest word above the place that overlaps it across stops the growth just under that word. A
place with no word in the way grows to the full height. Pure: bytes in, tops out.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

import pymupdf

from signora.modules.typesetting.mupdf import MUPDF_LOCK
from signora.modules.typesetting.sizes import Measured

# The least height a signature is drawn at, in points (its frame's words and the mark readable).
SIGNATURE_MIN_HEIGHT = 36.0
GAP = 1.5  # points kept clear under the agreement's text above a signature


def mark_top(rect: Sequence[float], measured: float | None) -> float:
    """The top of a signature's box: the measured room when there is one, else the full height;
    never lower than the place's own top (a tall place is drawn as it is)."""
    _, y0, _, y1 = rect
    grown = y1 - SIGNATURE_MIN_HEIGHT if measured is None else measured
    return min(y0, grown)


def mark_tops(pdf: bytes, places: Sequence[Measured]) -> dict[uuid.UUID, float]:
    """Each place's top: grown to ``SIGNATURE_MIN_HEIGHT`` above its line, or to just under the
    lowest word above it that overlaps it across. O(W + P * W) per page for W words and P places
    (a page has a few signature places)."""
    by_page: dict[int, list[Measured]] = defaultdict(list)
    for place in places:
        by_page[place.page].append(place)
    tops: dict[uuid.UUID, float] = {}
    with MUPDF_LOCK, pymupdf.open(stream=pdf, filetype="pdf") as document:
        for number, wanted in by_page.items():
            if not 1 <= number <= document.page_count:
                continue
            page = document.load_page(number - 1)
            words = [
                pymupdf.Rect(word[:4]) * page.rotation_matrix
                for word in page.get_text("words")
                if str(word[4]).strip()
            ]
            for place in wanted:
                x0, y0, x1, y1 = place.rect
                full = y1 - SIGNATURE_MIN_HEIGHT
                in_the_way = [
                    word.y1
                    for word in words
                    if word.x1 > x0
                    and word.x0 < x1  # overlaps the place across
                    and full < word.y1 <= y0 + 0.5  # above the place, within the growth
                ]
                top = max(in_the_way) + GAP if in_the_way else full
                tops[place.id] = min(y0, max(full, top))
    return tops
