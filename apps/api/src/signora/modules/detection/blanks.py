"""Blanks marked in a document's text (LLD §2.4): underscores, placeholders, checkbox glyphs.

A Word file converted to PDF, or a printed agreement, has no form fields, but its blanks are marked
in its text. Each becomes a field with its exact position. In a fillable PDF, only the blanks no
form field covers are added (§2.2). Blanks marked by nothing are the AI's ``extra_fields``.
"""

from __future__ import annotations

import re

import pymupdf

from signora.modules.detection.geometry import Box, RowIndex, center, cut
from signora.modules.detection.page_text import Marked, PageText, pages
from signora.modules.detection.reading import FieldKind, FoundField, Placement

UNDERSCORES = re.compile(r"_{3,}")
PLACEHOLDER = re.compile(r"\[[^\[\]]{2,80}\]|\{\{[^{}]{1,80}\}\}|«[^«»]{1,80}»|<<[^<>]{1,80}>>")
CHECKBOX_GLYPHS = frozenset({"☐", "□", "❑", "❒", "▢"})
RUN_GAP = 6.0  # runs on one row closer than this are one blank ("____ ____" typed in two goes)
TEXT_MAX = 160
OPTION_TEXT_MAX = 400


def _runs(page: pymupdf.Page) -> list[Box]:
    """Each run of underscores. A word may hold text and a run ("Date:_____"): the run's part of the
    word is its share of the characters."""
    boxes: list[Box] = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        for match in UNDERSCORES.finditer(text):
            width = (x1 - x0) / max(len(text), 1)
            boxes.append((x0 + width * match.start(), y0, x0 + width * match.end(), y1))
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
    ("[Describe the permitted" / "purpose]")."""
    found: list[tuple[Box, str, list[Box]]] = []
    for block in page.get_text("dict")["blocks"]:
        lines = ["".join(span["text"] for span in line["spans"]) for line in block.get("lines", [])]
        for match in PLACEHOLDER.finditer(" ".join(lines)):
            hits = page.search_for(match.group(0), clip=_grown(block["bbox"]))
            if hits:
                found.append((tuple(hits[0]), match.group(0), [tuple(h) for h in hits[1:]]))
    return found


def _grown(bbox: Box) -> pymupdf.Rect:
    x0, y0, x1, y1 = bbox
    return pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2)


def _glyphs(page: pymupdf.Page) -> list[Box]:
    return [(w[0], w[1], w[2], w[3]) for w in page.get_text("words") if w[4] in CHECKBOX_GLYPHS]


def _displayed(page: pymupdf.Page, box: Box) -> Box:
    shown = pymupdf.Rect(box) * page.rotation_matrix
    shown.normalize()
    return (round(shown.x0, 1), round(shown.y0, 1), round(shown.x1, 1), round(shown.y1, 1))


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
        for ref, kind, box in refs:
            option_text = None
            if kind == "checkbox":  # its words: up to the next glyph on the row
                row = [
                    g[0] for g in glyphs if abs(center(g)[1] - center(box)[1]) < 3 and g[0] > box[2]
                ]
                region = (box[2], box[1] - 2, min(row) - 1 if row else page.rect.width, box[3] + 2)
                option_text = cut(text.compose(region, skip=ref), OPTION_TEXT_MAX)
            holder = placeholder_of.get(ref)
            placement = Placement(
                page=number,
                rect=_displayed(page, box),
                option_text=option_text,
                continued=[_displayed(page, rest) for rest in holder[2]] if holder else [],
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
