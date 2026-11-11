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
        fields = list(places)
        self._taken: RowIndex[None] = RowIndex((box, None) for box in [*words, *fields])
        self._fields: RowIndex[None] = RowIndex((box, None) for box in fields)
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
        self._fields.add(box, None)

    def field_after(self, label: Box) -> bool:
        """Whether a field already sits right after a label on its row (where its blank would
        begin): the blank is that field, not a new one."""
        start = label[2] + LABEL_GAP
        return any(
            same_row(other, label) and other[2] > start and other[0] <= start + MIN_WIDTH
            for other, _ in self._fields.near(label[1], label[3])
        )

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
        """The free space after a label, one text line tall and at least ``MIN_WIDTH`` wide; None
        when there is none.

        - Something printed after the label on its row (a value, the rest of a sentence, another
          column): the blank can only be between them.
        - Nothing after it (the label ends its line): the rest of the line, or, when that is too
          short, the line below, from the label's left edge.
        """
        if not self._upright:
            return None
        x0, y0, x1, y1 = label
        start = x1 + LABEL_GAP
        after = self._first_after(start, y0, y1, row=label)
        if after is not None:
            return (
                (start, y0, after - CLEARANCE, y1)
                if after - CLEARANCE - start >= MIN_WIDTH
                else None
            )
        if self._right - start >= MIN_WIDTH:
            return (start, y0, self._right, y1)
        top, bottom = y1 + CLEARANCE, y1 + CLEARANCE + (y1 - y0)
        below = self._first_after(x0, top, bottom, row=None)
        end = below - CLEARANCE if below is not None else self._right
        return (x0, top, end, bottom) if end - x0 >= MIN_WIDTH else None

    def _first_after(
        self, start: float, top: float, bottom: float, row: Box | None
    ) -> float | None:
        """Where the first word or field after ``start`` begins in the band, ``start`` itself when
        one covers it, None when the band is clear to the right. ``row``: only what shares that
        row counts (a word of the line above or below that merely touches the band does not)."""
        first: float | None = None
        for other, _ in self._taken.near(top, bottom):
            in_band = (
                same_row(other, row) if row is not None else other[1] < bottom and top < other[3]
            )
            if in_band and other[2] > start:
                begins = max(other[0], start)
                first = begins if first is None else min(first, begins)
        return first


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

    def locate_after(self, number: int, words: str, near: Sequence[Box]) -> Box | None:
        """Where a blank given by the words before it goes, without taking it. The printing of
        the words is chosen first: the one closest to ``near`` (the party's own places on the
        page), and the blank is the room after that printing or nothing. The room after another
        printing is never taken instead: it belongs to whoever's places are near it (a label
        printed in two signature columns). With no ``near`` on the page, the first printing in
        reading order with room after it. O(H·N) for H printings and N nearby places."""
        space = self.page(number)
        if space is None:
            return None
        hits = space.find(words)
        if near:
            nearest = self._nearest(hits, near)
            return space.room_after(nearest) if nearest is not None else None
        return next((room for hit in hits if (room := space.room_after(hit))), None)

    def field_after(self, number: int, words: str, near: Sequence[Box]) -> bool:
        """Whether a field already sits after the party's printing of the words (the one
        ``locate_after`` would choose; with no ``near``, any printing)."""
        space = self.page(number)
        if space is None:
            return False
        hits = space.find(words)
        chosen = [self._nearest(hits, near)] if near else hits
        return any(hit is not None and space.field_after(hit) for hit in chosen)

    @staticmethod
    def _nearest(hits: Sequence[Box], near: Sequence[Box]) -> Box | None:
        return min(hits, key=lambda hit: min(_distance(hit, o) for o in near), default=None)

    def place_after(self, number: int, words: str, near: Sequence[Box]) -> Box | None:
        """``locate_after``, and the place is then taken: nothing placed later may overlap it."""
        room = self.locate_after(number, words, near)
        page = self.page(number)
        if room is not None and page is not None:
            page.take(room)
        return room


def _distance(a: Box, b: Box) -> float:
    (ax, ay), (bx, by) = center(a), center(b)
    return math.hypot(ax - bx, ay - by)
