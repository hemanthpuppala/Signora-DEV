"""The words of one page around its fields: labels, option text, text inside a box (LLD §2.3-2.4).

Lines are rebuilt from words: a word inside a field's box belongs to that box, and a line is split
where a box sits, so "Signature ______ Date: ____" gives the labels "Signature" and "Date:". All of
it is in the page's unrotated space, where both the text layer and the widgets live.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

import pymupdf

from signora.modules.detection.geometry import (
    Box,
    RowIndex,
    center,
    inside,
    overlaps_horizontally,
    same_row,
)


def pages(document: pymupdf.Document) -> Iterator[tuple[int, pymupdf.Page]]:
    """Each page with its number, from 1."""
    for index in range(document.page_count):
        yield index + 1, document.load_page(index)


LABEL_GAP = 18.0  # a label above or below a field sits within this many points of it
FAR_ABOVE = 48.0  # a heading over a lone line ("Print Name" two rows up) sits within this many
CAPTION_SHARE = 0.45  # a form cell's caption sits in this top share of the field's own box
TOUCH = 2.0  # points a caption's box may overlap the field it sits on (tight form layouts)
UNDERSCORES = re.compile(r"_{3,}")  # a typed blank: three or more underscores
# Leading characters that are not part of a label: stray marks, bullets, dashes before the words.
LEAD = re.compile(r"^[^\w(\[\"\u201c\u2018'$#\u00a7]+")
ROW_TOLERANCE = 4.0  # words whose centres are this close vertically are on one row
LEFT_COLUMNS = 40.0  # left labels are grouped into columns this wide, then read top to bottom


def _share(box: Box, text: str, start: int, end: int) -> Box:
    """The part of a word's box that characters ``start:end`` take: their share of its width."""
    x0, y0, x1, y1 = box
    width = (x1 - x0) / max(len(text), 1)
    return (x0 + width * start, y0, x0 + width * end, y1)


def split_at_runs(text: str, box: Box) -> list[tuple[str, Box, bool]]:
    """A word cut where its underscore runs are: each piece with its box and whether it is a run.
    "20____" gives "20" (words printed before a blank) and the run; a word with no run is itself."""
    pieces: list[tuple[str, Box, bool]] = []
    at = 0
    for match in UNDERSCORES.finditer(text):
        if match.start() > at:
            pieces.append((text[at : match.start()], _share(box, text, at, match.start()), False))
        pieces.append((match.group(), _share(box, text, match.start(), match.end()), True))
        at = match.end()
    if at < len(text):
        pieces.append((text[at:], _share(box, text, at, len(text)), False))
    return pieces


@dataclass(frozen=True)
class Line:
    text: str
    box: Box


@dataclass(frozen=True)
class Marked:
    """A field's box on the page, as option text refers to it: ``{ref}`` or ``{ref=value}``."""

    ref: str
    value: str | None
    box: Box


class PageText:
    """``marked``: every field box on the page. ``hidden``: more boxes whose words are not page text
    (the rest of a placeholder that wraps), without a marker of their own."""

    def __init__(
        self, page: pymupdf.Page, marked: list[Marked], hidden: Sequence[Box] = ()
    ) -> None:
        self._marked = RowIndex((item.box, item) for item in marked)
        covered = RowIndex(
            [(item.box, index) for index, item in enumerate(marked)] + [(box, -1) for box in hidden]
        )
        self._inside: dict[int, list[Line]] = {}
        free: list[Line] = []
        words: list[Line] = []
        segment: list[Line] = []
        current: tuple[int, int] | None = None

        def close() -> None:
            if segment:
                box = (
                    min(w.box[0] for w in segment),
                    min(w.box[1] for w in segment),
                    max(w.box[2] for w in segment),
                    max(w.box[3] for w in segment),
                )
                free.append(Line(" ".join(w.text for w in segment), box))
                segment.clear()

        for x0, y0, x1, y1, whole, block, line, _ in page.get_text("words"):
            if (block, line) != current:
                close()
                current = (block, line)
            # A word may hold a typed blank and words printed with it ("20____", "____,"): each
            # part is its own word, so the printed part stays page text (the year blank's "20").
            for text, part, _ in split_at_runs(whole, (x0, y0, x1, y1)):
                self._add(Line(text, part), covered, segment, words, close)
        close()
        self._free = RowIndex((line.box, line) for line in free)
        self._words = RowIndex((word.box, word) for word in words)

    def _add(
        self,
        word: Line,
        covered: RowIndex[int],
        segment: list[Line],
        words: list[Line],
        close: Callable[[], None],
    ) -> None:
        """One word: inside a field's box (its own appearance), or page text on the line. A field
        between the line's last word and this one also ends the line there: a blank drawn under
        spaces has no word on it ("Name:␣␣␣ Date:␣␣␣" is two labels, not one)."""
        holders = [index for _, index in covered.holding(center(word.box))]
        if holders:
            close()
            for index in holders:
                if index >= 0:
                    self._inside.setdefault(index, []).append(word)
            return
        if segment and self._field_between(segment[-1].box, word.box):
            close()
        segment.append(word)
        words.append(word)

    def _field_between(self, before: Box, after: Box) -> bool:
        """Whether a field on their row lies between two words of a line."""
        return any(
            same_row(box, after) and box[0] >= before[2] - 1 and box[2] <= after[0] + 1
            for box, _ in self._marked.near(after[1], after[3])
        )

    def left(self, box: Box) -> str | None:
        """Every line of the label cell to the left: lines that end left of the field and whose
        middle lies within its height (a heading and its caption; a row heading and the words
        leading up to the field). Otherwise the nearest line on the same row. Only what is printed
        after the nearest other field on the row: text before that field is that field's label
        ("Name: ____ Date: ____" gives the second "Date:", not "Name: · Date:")."""
        after = self._previous_edge(box)
        candidates = [
            line for _, line in self._free.near(box[1] - 3, box[3] + 3) if line.box[0] >= after - 1
        ]
        band = [
            line
            for line in candidates
            if line.box[2] <= box[0] + 2 and box[1] - 3 <= center(line.box)[1] <= box[3] + 3
        ]
        if not band:
            row = [
                line for line in candidates if line.box[2] <= box[0] + 2 and same_row(line.box, box)
            ]
            if row:
                return _label(max(row, key=lambda line: line.box[2]).text)
            # No words of its own after the previous field: a cell of a table's row takes the
            # row's heading, the label of the row's first field ("Print Name" for each party).
            first = self._first_on_row(box)
            return self.left(first) if first is not None else None
        band.sort(key=lambda line: (round(line.box[0] / LEFT_COLUMNS), line.box[1]))
        return _label(" · ".join(line.text for line in band))

    def _first_on_row(self, box: Box) -> Box | None:
        """The leftmost other field on the field's row that lies left of it, if any."""
        before = [
            other
            for other, _ in self._marked.near(box[1], box[3])
            if other != box and same_row(other, box) and other[2] <= box[0] + 2
        ]
        return min(before, key=lambda other: other[0], default=None)

    def _previous_edge(self, box: Box) -> float:
        """Where the nearest other field to the left on its row ends (else the page's edge)."""
        edges = [
            other[2]
            for other, _ in self._marked.near(box[1], box[3])
            if other != box and same_row(other, box) and other[2] <= box[0] + 2
        ]
        return max(edges, default=float("-inf"))

    def above(self, box: Box, reach: float = LABEL_GAP) -> str | None:
        """The nearest line over the field within ``reach``, overlapping it horizontally: its
        middle above the field's top edge (a form's caption may overlap the field's top). Never
        past another field between them: that line is the other field's."""
        over = [
            line
            for _, line in self._free.near(box[1] - reach, box[1])
            if center(line.box)[1] <= box[1]
            and box[1] - line.box[3] <= reach
            and overlaps_horizontally(line.box, box)
        ]
        if not over:
            return None
        nearest = max(over, key=lambda line: line.box[3])
        between = any(
            other != box
            and nearest.box[3] - TOUCH <= other[1]
            and other[3] <= box[1] + TOUCH
            and overlaps_horizontally(other, box)
            for other, _ in self._marked.near(nearest.box[3], box[1])
        )
        return None if between else _label(nearest.text)

    def below(self, box: Box) -> str | None:
        under = [
            line
            for _, line in self._free.near(box[3], box[3] + LABEL_GAP)
            if 0 <= line.box[1] - box[3] <= LABEL_GAP and overlaps_horizontally(line.box, box)
        ]
        return _label(min(under, key=lambda line: line.box[1]).text) if under else None

    def within(self, index: int) -> str | None:
        """The words drawn inside the field's box (usually its own appearance)."""
        return " ".join(word.text for word in self._inside.get(index, [])) or None

    def caption(self, index: int, box: Box) -> str | None:
        """Words printed in the top part of a form field's own box: the caption of a form's cell
        ("Year", "Make/Manufacturer" in the cell's corner, the box drawn over the whole cell)."""
        top = box[1] + (box[3] - box[1]) * CAPTION_SHARE
        words = [word for word in self._inside.get(index, []) if center(word.box)[1] <= top]
        return _label(" ".join(word.text for word in words)) if words else None

    def compose(self, region: Box, skip: str) -> str | None:
        """The words in a region in reading order, with every other field in it written as
        ``{ref}`` or ``{ref=value}``: how an option or a checkbox reads, its blanks included."""
        tokens = [
            (word.text, word.box)
            for _, word in self._words.near(region[1], region[3])
            if inside(center(word.box), region)
        ]
        tokens += [
            ("{" + item.ref + (f"={item.value}" if item.value else "") + "}", item.box)
            for _, item in self._marked.near(region[1], region[3])
            if item.ref != skip and inside(center(item.box), region)
        ]
        if not tokens:
            return None
        tokens.sort(key=lambda token: center(token[1])[1])
        rows: list[list[tuple[str, Box]]] = []
        for token in tokens:
            if rows and abs(center(token[1])[1] - center(rows[-1][0][1])[1]) <= ROW_TOLERANCE:
                rows[-1].append(token)
            else:
                rows.append([token])
        return " ".join(text for row in rows for text, _ in sorted(row, key=lambda t: t[1][0]))


def _label(text: str) -> str | None:
    """A label without the stray marks before its words; None when nothing is left."""
    return LEAD.sub("", text).strip() or None
