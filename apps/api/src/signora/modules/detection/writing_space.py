"""Free space to write in on a page (findings F2 and F10, `05b-detection-findings.md`).

One model of what a page leaves free, for every place detection has to size or find itself:

- **Room to sign** (F2): a blank's box is the box of its line's text, one text line tall; a
  signature or initials drawn to fit it would be smaller than the agreement's own text. It grows
  upward into the writing space above its line, the line kept as its bottom edge, up to
  ``SIGN_HEIGHT``.
- **Room after a label** (F10): a blank the AI found where the page marks nothing ("NAME:" and
  empty space) is given by the words printed right before it. Its place is the free space after
  those words on their row, or on the row below when that one is full, never the words themselves.

Space is free when no visible word and no field is in it. Words made only of spaces, zero-width
characters or soft hyphens draw nothing and leave it free. A form field's box is the author's and
is never changed (signing fills that form field). Everything is on the page as displayed, and only
on a page whose text reads upright as shown, where "above" and "after" are the reader's.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import pymupdf

from signora.modules.detection.geometry import Box, RowIndex, center, displayed, same_row

SIGN_HEIGHT = 36.0  # points: room for a signature, in the range e-signature fields are drawn at
CLEARANCE = 2.0  # points kept free from the nearest word or field
LABEL_GAP = 3.0  # points between a label and the box after it
MIN_WIDTH = 60.0  # points: the narrowest box a value is written in (a date at 10 pt fits)
GROWS = frozenset({"signature", "initials"})
# Characters that draw nothing: a word made only of these leaves its space free.
_INVISIBLE = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff\u00ad")


def visible(text: str) -> bool:
    """Whether a word draws anything: not only spaces, zero-width characters or soft hyphens."""
    return bool(text.translate(_INVISIBLE).strip())


def _reads_upright(page: pymupdf.Page) -> bool:
    """Whether most of the page's text reads left to right as the page is shown: only then are
    "above" and "after" the page's up and right. A line's direction is in the page's own space;
    the page's rotation turns it as shown."""
    turn = page.rotation_matrix
    upright = sideways = 0
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            shown = pymupdf.Point(line["dir"]) * turn - pymupdf.Point(0, 0) * turn
            if shown.x > 0.9:
                upright += 1
            else:
                sideways += 1
    return upright > sideways


class PageSpace:
    """What may not be written over on one page: its visible words and its fields' places. Each
    question looks only at the rows it concerns (``RowIndex``): O(k) for k neighbours."""

    def __init__(self, page: pymupdf.Page, places: Iterable[Box]) -> None:
        self._page = page
        words = [displayed(page, word[:4]) for word in page.get_text("words") if visible(word[4])]
        self._taken: RowIndex[None] = RowIndex((box, None) for box in [*words, *places])
        self._upright = _reads_upright(page)
        # The text's right edge: a box after a label runs to it at most, never into the margin.
        # The furthest word, or the left margin mirrored when the page's text is short (a form of
        # labels): pages are laid out with even margins.
        width = page.rect.width
        left = min((word[0] for word in words), default=0.0)
        self._right = max(max((word[2] for word in words), default=width), width - left)

    def take(self, box: Box) -> None:
        """A place now given to a field: nothing placed later may overlap it."""
        self._taken.add(box, None)

    def find(self, words: str) -> list[Box]:
        """Every place the words are printed on the page, as displayed, in reading order."""
        hits = [displayed(self._page, hit) for hit in self._page.search_for(words)]
        return sorted(hits, key=lambda box: (round(box[1]), box[0]))

    def room_above(self, box: Box) -> Box:
        """The box grown upward into the free space above it; never smaller than it was; kept as
        it is on a page whose text is not upright as shown."""
        if not self._upright:
            return box
        x0, y0, x1, y1 = box
        top = max(y1 - SIGN_HEIGHT, 0.0)
        for other, _ in self._taken.near(top, y0):
            above = other[3] <= y0 + 0.5
            if other != box and above and min(other[2], x1) - max(other[0], x0) > 0:
                top = max(top, other[3] + CLEARANCE)
        return (x0, min(top, y0), x1, y1)

    def room_after(self, label: Box) -> Box | None:
        """The free space after a label: on its row, from just after it to the next word or field
        (or the text's right edge); else on the row below, from the label's left edge. One text
        line tall, at least ``MIN_WIDTH`` wide; None when neither row has that much."""
        if not self._upright:
            return None
        x0, y0, x1, y1 = label
        start = x1 + LABEL_GAP
        on_row = self._free_from(start, (start, y0, self._right, y1), row=label)
        if on_row is not None:
            return on_row
        below = y1 + CLEARANCE
        return self._free_from(x0, (x0, below, self._right, below + (y1 - y0)), row=None)

    def _free_from(self, start: float, band: Box, row: Box | None) -> Box | None:
        """The band from ``start`` up to the first thing in it; None when something covers
        ``start`` or less than ``MIN_WIDTH`` is left. ``row``: only what shares that row counts
        (a word on the line above or below that merely touches the band does not)."""
        _, y0, right, y1 = band
        end = right
        for other, _ in self._taken.near(y0, y1):
            in_band = same_row(other, row) if row is not None else other[1] < y1 and y0 < other[3]
            if not in_band or other[2] <= start:
                continue
            if other[0] <= start:
                return None  # something sits where the box would begin
            end = min(end, other[0] - CLEARANCE)
        return (start, y0, end, y1) if end - start >= MIN_WIDTH else None


class DocumentSpace:
    """Each page's ``PageSpace``, built once when first asked for, from its fields' places."""

    def __init__(self, document: pymupdf.Document, places: dict[int, list[Box]]) -> None:
        self._document = document
        self._places = places
        self._pages: dict[int, PageSpace] = {}

    def page(self, number: int) -> PageSpace | None:
        """The page's space; None for a page the document does not have."""
        if not 1 <= number <= self._document.page_count:
            return None
        if number not in self._pages:
            page = self._document.load_page(number - 1)
            self._pages[number] = PageSpace(page, self._places.get(number, []))
        return self._pages[number]

    def place_after(self, number: int, words: str, near: Sequence[Box]) -> Box | None:
        """Where a blank given by the words before it goes: after the printing of those words
        that has room after it, the one closest to ``near`` (the same party's other places on
        the page; the first in reading order without any). The place is then taken. O(H·N) for H
        printings and N nearby places."""
        space = self.page(number)
        if space is None:
            return None
        candidates = [room for hit in space.find(words) if (room := space.room_after(hit))]
        if not candidates:
            return None
        if near:
            candidates.sort(key=lambda room: min(_distance(room, other) for other in near))
        space.take(candidates[0])
        return candidates[0]


def _distance(a: Box, b: Box) -> float:
    (ax, ay), (bx, by) = center(a), center(b)
    return math.hypot(ax - bx, ay - by)
