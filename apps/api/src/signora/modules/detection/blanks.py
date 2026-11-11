"""Blanks marked in a document's text (LLD §2.4): underscores, placeholders, checkbox glyphs.

A Word file converted to PDF, or a printed agreement, has no form fields, but its blanks are marked
in its text. Each becomes a field with its exact position. In a fillable PDF, only the blanks no
form field covers are added (§2.2). Blanks marked by nothing are the AI's ``extra_fields``.
"""

from __future__ import annotations

import re

import pymupdf

from signora.modules.detection.geometry import (
    TEXT_MAX,
    Box,
    RowIndex,
    center,
    cut,
    displayed,
)
from signora.modules.detection.page_text import Marked, PageText, pages
from signora.modules.detection.reading import FieldKind, FoundField, Placement
from signora.modules.review.values import OPTION_MAX

UNDERSCORES = re.compile(r"_{3,}")
PLACEHOLDER = re.compile(r"\[[^\[\]]{2,80}\]|\{\{[^{}]{1,80}\}\}|«[^«»]{1,80}»|<<[^<>]{1,80}>>")
CHECKBOX_GLYPHS = frozenset({"☐", "□", "❑", "❒", "▢"})
RUN_GAP = 6.0  # runs on one row closer than this are one blank ("____ ____" typed in two goes)


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


def _runs(page: pymupdf.Page) -> list[Box]:
    """Each run of underscores. A word may hold text and a run ("Date:_____"): the run's part of the
    word is its share of the characters."""
    boxes: list[Box] = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        boxes.extend(piece for _, piece, run in split_at_runs(text, (x0, y0, x1, y1)) if run)
    boxes.sort(key=lambda b: (round(center(b)[1]), b[0]))
    merged: list[Box] = []
    for box in boxes:
        last = merged[-1] if merged else None
        if last and abs(center(last)[1] - center(box)[1]) < 2 and box[0] - last[2] < RUN_GAP:
            merged[-1] = (last[0], min(last[1], box[1]), box[2], max(last[3], box[3]))
        else:
            merged.append(box)
    return merged


def _placeholders(page: pymupdf.Page) -> list[tuple[Box, str, list[Box]]]:
    """Each placeholder: its first box, its text, and the boxes of its other lines when it wraps
    ("[Describe the permitted" / "purpose]"). A placeholder is matched in its block's text, then
    each line's part of it is looked up on that line, so the same placeholder twice on a page (or
    twice on a line: "[Name] … [Name]") gets a box of its own each time."""
    found: list[tuple[Box, str, list[Box]]] = []
    for block in page.get_text("dict")["blocks"]:
        lines = [
            ("".join(span["text"] for span in line["spans"]), tuple(line["bbox"]))
            for line in block.get("lines", [])
        ]
        starts: list[int] = []
        at = 0
        for text, _ in lines:
            starts.append(at)
            at += len(text) + 1  # the lines are joined by one space
        joined = " ".join(text for text, _ in lines)
        taken: dict[tuple[int, str], int] = {}  # (line, part) -> boxes of it already used
        for match in PLACEHOLDER.finditer(joined):
            boxes: list[Box] = []
            for index, (text, bbox) in enumerate(lines):
                low, high = (
                    max(match.start(), starts[index]),
                    min(match.end(), starts[index] + len(text)),
                )
                if low >= high:
                    continue
                part = joined[low:high]
                hits = page.search_for(part, clip=_grown(bbox))  # in reading order along the line
                used = taken.get((index, part), 0)
                taken[(index, part)] = used + 1
                if used < len(hits):
                    boxes.append(tuple(hits[used]))
            if boxes:
                found.append((boxes[0], match.group(0), boxes[1:]))
    return found


def _grown(bbox: Box) -> pymupdf.Rect:
    x0, y0, x1, y1 = bbox
    return pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2)


def _glyphs(page: pymupdf.Page) -> list[Box]:
    return [(w[0], w[1], w[2], w[3]) for w in page.get_text("words") if w[4] in CHECKBOX_GLYPHS]


ROW_TOLERANCE = 3.0  # points: glyphs whose centres are this close share a row


def _next_on_row(glyphs: list[Box], edge: float) -> dict[Box, float]:
    """For each checkbox glyph, where the next one on its row starts (else the page's ``edge``):
    its option words lie between. One sort by row, then by x: O(G log G)."""
    ordered = sorted(glyphs, key=lambda box: (center(box)[1], box[0]))
    rows: list[list[Box]] = []
    for box in ordered:
        if rows and abs(center(box)[1] - center(rows[-1][0])[1]) < ROW_TOLERANCE:
            rows[-1].append(box)
        else:
            rows.append([box])
    after: dict[Box, float] = {}
    for row in rows:
        row.sort(key=lambda box: box[0])
        for box, following in zip(row, [*row[1:], None], strict=True):
            after[box] = following[0] if following is not None else edge
    return after


def find_blanks(
    document: pymupdf.Document, *, covered: dict[int, list[Box]] | None = None
) -> list[FoundField]:
    """Every blank, skipping those under a form field (``covered``: unrotated boxes per page)."""
    found: list[FoundField] = []
    for number, page in pages(document):
        under = RowIndex((box, None) for box in (covered or {}).get(number, []))

        def free(box: Box, under: RowIndex[None] = under) -> bool:
            return next(under.holding(center(box)), None) is None

        runs = [box for box in _runs(page) if free(box)]
        holders = [item for item in _placeholders(page) if free(item[0])]
        glyphs = [box for box in _glyphs(page) if free(box)]
        if not (runs or holders or glyphs):
            continue
        refs: list[tuple[str, FieldKind, Box]] = [
            *[(f"blank:{number}:r{i}", "blank", box) for i, box in enumerate(runs)],
            *[(f"blank:{number}:p{i}", "blank", box) for i, (box, _, _) in enumerate(holders)],
            *[(f"blank:{number}:c{i}", "checkbox", box) for i, box in enumerate(glyphs)],
        ]
        text = PageText(
            page,
            [Marked(ref, None, box) for ref, _, box in refs],
            hidden=[rest for _, _, others in holders for rest in others],
        )
        placeholder_of = {f"blank:{number}:p{i}": item for i, item in enumerate(holders)}
        # Text positions are in the page's own (unrotated) space: the row ends at its edge.
        next_on_row = _next_on_row(glyphs, page.cropbox.width)
        for ref, kind, box in refs:
            option_text = None
            if kind == "checkbox":  # its words: up to the next glyph on the row
                region = (box[2], box[1] - 2, next_on_row[box] - 1, box[3] + 2)
                option_text = cut(text.compose(region, skip=ref), OPTION_MAX)
            holder = placeholder_of.get(ref)
            placement = Placement(
                page=number,
                rect=displayed(page, box),
                option_text=option_text,
                continued=[displayed(page, rest) for rest in holder[2]] if holder else [],
            )
            found.append(
                FoundField(
                    ref=ref,
                    kind=kind,
                    placements=[placement],
                    label_left=cut(text.left(box), TEXT_MAX),
                    label_above=cut(text.above(box), TEXT_MAX),
                    label_below=cut(text.below(box), TEXT_MAX) if kind == "blank" else None,
                    value=holder[1] if holder else None,
                    sample_value=holder is not None,
                )
            )
    return found
