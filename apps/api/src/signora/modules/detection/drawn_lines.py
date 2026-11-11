"""Blank lines drawn as graphics (findings F1, `05b-detection-findings.md`).

A blank is a line with nothing written on it. Word types its lines as underscores, which the text
marks find (``blanks``); a word processor's underline on spaces, a layout tool's rule and a
government form's line are drawn as graphics and have no text. This finds those: a thin horizontal
line on the page is a blank where nothing visible is printed on it.

What is printed on a line decides, character by character (a word's box may span the line and a
comma after it): spaces, zero-width characters and soft hyphens draw nothing; any other character
is writing, and the line is cut where it sits, so an underline under "Name:" and the spaces after
it gives the stretch after the label, and an underlined word gives nothing.

A line drawn in pieces is one line (a table's row rule is often drawn once per column), and is
judged whole. Lines that are not blanks:

- a line drawn in white or fully transparent (it shows nothing);
- an unlabelled rule across most of the text's width (a separator, a table's row rule); a labelled
  line is a blank whatever its length ("Address: ____" across the page);
- a line whose end meets a vertical line (a table's or a box's border; captioned boxes are
  topic 8's);
- in the top or bottom margin, a line with no label printed to its left on its row (a header or
  footer rule; initials in a footer, "Initials: ____", have their label and are kept);
- a line under a form field or under a blank already found in the text.

Everything is in the page's own (unrotated) space, as its text and drawings are. One pass over a
page's drawings and one over its characters, then a row index: O(D log D + C) a page.
"""

from __future__ import annotations

from collections.abc import Iterable

import pymupdf

from signora.modules.detection.geometry import Box, RowIndex
from signora.modules.detection.writing_space import visible

THICKNESS_MAX = 2.0  # points: a drawn line or bar no thicker than this
LENGTH_MIN = 20.0  # points: shorter is a dash or a glyph's stroke, not room to write
JOIN_GAP = 1.5  # points: pieces of one line closer than this are drawn as one line
ROW_HEIGHT = 0.6  # points: pieces this close in height are on one row
TEXT_ABOVE = 12.0  # points above a line where what is written on it sits
FULL_WIDTH = 0.8  # a line wider than this share of the text's width is a separator
MARGIN = 0.1  # the top and bottom share of a page: header and footer
LABEL_REACH = 72.0  # points: in a margin, a label to the line's left on its row, this close
TOUCH = 2.0  # points: a vertical line this close to a line's end meets it
MERGE_GAP = 6.0  # points: empty stretches on one line closer than this are one blank
INK_LIGHTEST = 0.9  # a colour whose every channel is lighter than this is white: no ink

Line = tuple[float, float, float]  # x0, x1, y: a horizontal line
Upright = tuple[float, float, float]  # x, y0, y1: a vertical line


def _lines(page: pymupdf.Page) -> tuple[list[Line], list[Upright]]:
    """The page's thin horizontal lines, pieces joined, at least ``LENGTH_MIN`` long, and its
    thin vertical lines: stroked segments, and rectangles or quads that are bars. Each once (a
    path is often both stroked and filled)."""
    pieces: set[Line] = set()
    down: set[Upright] = set()
    for drawing in page.get_drawings():
        if not _inked(drawing):
            continue  # white or transparent: draws nothing a person sees
        for item in drawing["items"]:
            if item[0] == "l":
                rect = pymupdf.Rect(item[1], item[2])
                rect.normalize()
            elif item[0] == "re":
                rect = pymupdf.Rect(item[1])
            elif item[0] == "qu":
                rect = item[1].rect
            else:
                continue
            if rect.height <= THICKNESS_MAX and rect.width > 0:
                pieces.add((round(rect.x0, 1), round(rect.x1, 1), round(rect.y1, 1)))
            elif rect.width <= THICKNESS_MAX and rect.height >= THICKNESS_MAX * 2:
                down.add((round((rect.x0 + rect.x1) / 2, 1), rect.y0, rect.y1))
    # Rows first (pieces within 0.6 pt of height), then left to right within a row: only pieces
    # that touch side by side are one line, never two lines of a row that are apart.
    rows: list[list[Line]] = []
    for piece in sorted(pieces, key=lambda line: line[2]):
        if rows and piece[2] - rows[-1][0][2] <= ROW_HEIGHT:
            rows[-1].append(piece)
        else:
            rows.append([piece])
    joined: list[Line] = []
    for row in rows:
        y = row[0][2]
        current: Line | None = None
        for x0, x1, _ in sorted(row):
            if current is not None and x0 - current[1] <= JOIN_GAP:
                current = (current[0], max(current[1], x1), y)
            else:
                if current is not None:
                    joined.append(current)
                current = (x0, x1, y)
        if current is not None:
            joined.append(current)
    return [line for line in joined if line[1] - line[0] >= LENGTH_MIN], list(down)


def _inked(drawing: dict[str, object]) -> bool:
    """Whether a drawing shows: a stroke or fill colour that is not white, not fully transparent."""
    kind = str(drawing.get("type") or "")
    paints = []
    if "s" in kind:
        paints.append((drawing.get("color"), drawing.get("stroke_opacity")))
    if "f" in kind:
        paints.append((drawing.get("fill"), drawing.get("fill_opacity")))
    for colour, opacity in paints:
        shade = colour if isinstance(colour, (tuple, list)) else ()
        if shade and min(shade) < INK_LIGHTEST and (opacity is None or float(str(opacity)) > 0):
            return True
    return False


def _written(page: pymupdf.Page) -> list[Box]:
    """Every visible character on the page, by its own box."""
    boxes: list[Box] = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for char in span["chars"]:
                    if visible(char["c"]):
                        boxes.append(tuple(char["bbox"]))
    return boxes


def _on_row(box: Box, y: float) -> bool:
    """Whether a character sits on the text row a line at ``y`` is drawn under."""
    return y - TEXT_ABOVE <= (box[1] + box[3]) / 2 <= y + 1


def _meets(uprights: Iterable[Upright], x: float, y: float) -> bool:
    return any(abs(ux - x) <= TOUCH and y0 - TOUCH <= y <= y1 + TOUCH for ux, y0, y1 in uprights)


def _labelled(line: Line, written: RowIndex[None]) -> bool:
    """Whether something is printed just left of the line on its row (its label)."""
    x0, _, y = line
    return any(
        _on_row(box, y) and x0 - LABEL_REACH <= box[2] <= x0 + 1
        for box, _ in written.near(y - TEXT_ABOVE, y + 1)
    )


def _empty_stretches(line: Line, written: RowIndex[None]) -> list[tuple[float, float]]:
    """The parts of a line with no visible character written on it, at least ``LENGTH_MIN``."""
    x0, x1, y = line
    taken = sorted(
        (box[0] - 1, box[2] + 1)
        for box, _ in written.near(y - TEXT_ABOVE, y + 1)
        if x0 <= (box[0] + box[2]) / 2 <= x1 and _on_row(box, y)
    )
    stretches: list[tuple[float, float]] = []
    at = x0
    for start, end in taken:
        if start - at >= LENGTH_MIN:
            stretches.append((at, start))
        at = max(at, end)
    if x1 - at >= LENGTH_MIN:
        stretches.append((at, x1))
    return stretches


def _merge(boxes: list[Box]) -> list[Box]:
    """Empty stretches on one line closer than ``MERGE_GAP`` are one blank."""
    merged: list[Box] = []
    for box in sorted(boxes, key=lambda b: (round(b[3]), b[0])):
        last = merged[-1] if merged else None
        if last and abs(last[3] - box[3]) < 1 and box[0] - last[2] < MERGE_GAP:
            merged[-1] = (last[0], min(last[1], box[1]), box[2], max(last[3], box[3]))
        else:
            merged.append(box)
    return merged


def drawn_blanks(page: pymupdf.Page, taken: Iterable[Box]) -> list[Box]:
    """The page's drawn lines that are blanks, each as the line with the text row above it.
    ``taken``: form fields and blanks already found; a line under one is not another."""
    across, down = _lines(page)
    if not across:
        return []
    written_boxes = _written(page)
    written: RowIndex[None] = RowIndex((box, None) for box in written_boxes)
    found: RowIndex[None] = RowIndex((box, None) for box in taken)
    left = min((box[0] for box in written_boxes), default=0.0)
    right = max((box[2] for box in written_boxes), default=page.cropbox.width)
    height = page.cropbox.height
    blanks: list[Box] = []
    for line in across:
        x0, x1, y = line
        long = x1 - x0 > FULL_WIDTH * max(right - left, LENGTH_MIN)
        if long and not _labelled(line, written):
            continue  # a separator or a table's row rule ("Address: ____" across the page is kept)
        if _meets(down, x0, y) or _meets(down, x1, y):
            continue  # a table's or a box's border
        in_margin = y < height * MARGIN or y > height * (1 - MARGIN)
        if in_margin and not _labelled(line, written):
            continue  # a header or footer rule
        for start, end in _empty_stretches(line, written):
            box = (start, y - TEXT_ABOVE, end, y + 1)
            under = any(
                min(other[2], end) - max(other[0], start) > (end - start) / 2
                for other, _ in found.near(box[1], box[3])
                if other[1] < box[3] and box[1] < other[3]
            )
            if not under:
                blanks.append(box)
    return _merge(blanks)
