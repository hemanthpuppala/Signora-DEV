"""The words of one page around its fields: labels, option text, text inside a box (LLD §2.3-2.4).

Lines are rebuilt from words: a word inside a field's box belongs to that box, and a line is split
where a box sits, so "Signature ______ Date: ____" gives the labels "Signature" and "Date:". All of
it is in the page's unrotated space, where both the text layer and the widgets live.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
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
ROW_TOLERANCE = 4.0  # words whose centres are this close vertically are on one row
LEFT_COLUMNS = 40.0  # left labels are grouped into columns this wide, then read top to bottom


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
        self._inside: dict[int, list[str]] = {}
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

        for x0, y0, x1, y1, text, block, line, _ in page.get_text("words"):
            word = Line(text, (x0, y0, x1, y1))
            if (block, line) != current:
                close()
                current = (block, line)
            holders = [index for _, index in covered.holding(center(word.box))]
            if holders:
                close()
                for index in holders:
                    if index >= 0:
                        self._inside.setdefault(index, []).append(text)
                continue
            segment.append(word)
            words.append(word)
        close()
        self._free = RowIndex((line.box, line) for line in free)
        self._words = RowIndex((word.box, word) for word in words)

    def left(self, box: Box) -> str | None:
        """Every line of the label cell to the left: lines that end left of the field and whose
        middle lies within its height (a heading and its caption; a row heading and the words
        leading up to the field). Otherwise the nearest line on the same row."""
        candidates = [line for _, line in self._free.near(box[1] - 3, box[3] + 3)]
        band = [
            line
            for line in candidates
            if line.box[2] <= box[0] + 2 and box[1] - 3 <= center(line.box)[1] <= box[3] + 3
        ]
        if not band:
            row = [
                line for line in candidates if line.box[2] <= box[0] + 2 and same_row(line.box, box)
            ]
            return max(row, key=lambda line: line.box[2]).text if row else None
        band.sort(key=lambda line: (round(line.box[0] / LEFT_COLUMNS), line.box[1]))
        return " · ".join(line.text for line in band)

    def above(self, box: Box) -> str | None:
        over = [
            line
            for _, line in self._free.near(box[1] - LABEL_GAP, box[1])
            if 0 <= box[1] - line.box[3] <= LABEL_GAP and overlaps_horizontally(line.box, box)
        ]
        return max(over, key=lambda line: line.box[3]).text if over else None

    def below(self, box: Box) -> str | None:
        under = [
            line
            for _, line in self._free.near(box[3], box[3] + LABEL_GAP)
            if 0 <= line.box[1] - box[3] <= LABEL_GAP and overlaps_horizontally(line.box, box)
        ]
        return min(under, key=lambda line: line.box[1]).text if under else None

    def within(self, index: int) -> str | None:
        """The words drawn inside the field's box (usually its own appearance)."""
        return " ".join(self._inside.get(index, [])) or None

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
