"""Room to sign on a line (findings F2, `05b-detection-findings.md`).

A blank's box is the box of its line's text, one text line tall; a signature or initials drawn to
fit it would be smaller than the agreement's own text. A signature sits on its line and takes the
writing space above it: the box grows upward, the line kept as its bottom edge, up to
``SIGN_HEIGHT`` and never over a visible word or another field. A form field's box is the author's
and is never changed (signing fills that form field). Everything here is on the page as displayed.
"""

from __future__ import annotations

from collections.abc import Iterable

import pymupdf

from signora.modules.detection.geometry import Box, RowIndex, displayed

SIGN_HEIGHT = 36.0  # points: room for a signature, in the range e-signature fields are drawn at
CLEARANCE = 2.0  # points kept free below the nearest word or field above
GROWS = frozenset({"signature", "initials"})
# Characters that draw nothing: a word made only of these leaves its space free.
_INVISIBLE = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff\u00ad")


def visible(text: str) -> bool:
    """Whether a word draws anything: not only spaces, zero-width characters or soft hyphens."""
    return bool(text.translate(_INVISIBLE).strip())


def _reads_upright(page: pymupdf.Page) -> bool:
    """Whether most of the page's text reads left to right as the page is shown: only then is
    "above the line" the page's up. A line's direction is in the page's own space; the page's
    rotation turns it as shown."""
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
    """What may not be written over on one page: its visible words and its fields' places."""

    def __init__(self, page: pymupdf.Page, places: Iterable[Box]) -> None:
        words = [displayed(page, word[:4]) for word in page.get_text("words") if visible(word[4])]
        self._taken: RowIndex[None] = RowIndex((box, None) for box in [*words, *places])
        self._upright = _reads_upright(page)

    def room_above(self, box: Box) -> Box:
        """The box grown upward into the free space above it; never smaller than it was. On a
        page whose text does not read upright as shown, "above" is not the page's up, and the box
        is kept as it is. Only what lies in the rows above it is looked at (``RowIndex``): O(k)
        for k neighbours."""
        if not self._upright:
            return box
        x0, y0, x1, y1 = box
        top = max(y1 - SIGN_HEIGHT, 0.0)
        for other, _ in self._taken.near(top, y0):
            above = other[3] <= y0 + 0.5
            if other != box and above and min(other[2], x1) - max(other[0], x0) > 0:
                top = max(top, other[3] + CLEARANCE)
        return (x0, min(top, y0), x1, y1)
