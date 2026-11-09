"""The document as the AI reads it: layout text with field markers (LLD §2.5).

Each page becomes rows of words at their horizontal position, so table columns line up, and every
field becomes a marker where it sits (``⟦f8⟧``, ``⟦f4=Choice1⟧`` for a radio option), centred in its
box. Text drawn inside a field's box is left out: the fields table carries it. Tested against
Markdown converters, which misplaced columns or the order within a cell (ADR-DET2).
"""

from __future__ import annotations

import pymupdf

from signora.modules.detection.geometry import Box, RowIndex, center, unrotated
from signora.modules.detection.page_text import pages
from signora.modules.detection.reading import Reading
from signora.modules.detection.untrusted import clean

POINTS_PER_COLUMN = 4.5  # one character column per 4.5 pt: a US Letter page is about 136 wide
ROW_TOLERANCE = 4.5  # words whose centres are this close are on one row
PARAGRAPH_GAP = 14.0  # a larger gap between rows is an empty line


def layout_text(document: pymupdf.Document, reading: Reading) -> str:
    """O(W log W) per page for W words (sorting); every lookup goes through a row index."""
    rendered = []
    for number, page in pages(document):
        markers: list[tuple[str, Box, bool]] = []  # (text, box, is a marker)
        hidden: list[Box] = []
        # Markers only for the fields the AI is asked about; a field nobody fills (read-only,
        # calculated, hidden) reads as the text drawn in it.
        for field in reading.asked:
            for placement in field.placements:
                if placement.page != number:
                    continue
                label = (
                    f"⟦{field.id}={placement.value}⟧" if field.kind == "radio" else f"⟦{field.id}⟧"
                )
                markers.append((label, unrotated(page, placement.rect), True))
                hidden.extend(unrotated(page, rest) for rest in placement.continued)
        covering = RowIndex(
            [(box, None) for _, box, _ in markers] + [(box, None) for box in hidden]
        )
        tokens = list(markers)
        for x0, y0, x1, y1, word, *_ in page.get_text("words"):
            box = (x0, y0, x1, y1)
            if next(covering.holding(center(box)), None) is None:
                tokens.append((clean(word), box, False))
        tokens = [token for token in tokens if token[0]]
        tokens.sort(key=lambda token: center(token[1])[1])
        rows: list[list[tuple[str, Box, bool]]] = []
        for token in tokens:
            if rows and center(token[1])[1] - center(rows[-1][0][1])[1] <= ROW_TOLERANCE:
                rows[-1].append(token)
            else:
                rows.append([token])
        lines = [f"--- page {number} ---"]
        previous_bottom: float | None = None
        for row in rows:
            top = min(box[1] for _, box, _ in row)
            if previous_bottom is not None and top - previous_bottom > PARAGRAPH_GAP:
                lines.append("")
            previous_bottom = max(box[3] for _, box, _ in row)
            out = ""
            for word, box, is_marker in sorted(row, key=lambda token: token[1][0]):
                # A marker is centred in its box, so it lines up under its column's heading.
                x = center(box)[0] - len(word) * POINTS_PER_COLUMN / 2 if is_marker else box[0]
                column = int(max(x, 0) / POINTS_PER_COLUMN)
                out += " " * max(column - len(out), 1 if out else 0) + word
            lines.append(out.rstrip())
        rendered.append("\n".join(lines))
    return "\n\n".join(rendered)
