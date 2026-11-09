"""The rule that draws a value in its box (Phase 7b LLD): one definition for the preview's numbers
and the signed PDF. Pure but for reading the font's widths.

A value is drawn left-aligned on the box's line (its bottom edge, where a blank's underline is), at
the size of the agreement's text around the box; a value too wide is drawn smaller, down to
``MIN_SIZE``; wider still, it does not fit and is refused.
"""

from __future__ import annotations

from collections.abc import Sequence

from signora.modules.typesetting.fonts import metrics

MIN_SIZE = 6.0  # points: smaller is not readable on paper
FALLBACK_RATIO = 0.72  # without the agreement's text size: this share of the box's height
FALLBACK_CAP = 11.0  # ... and no larger than body text
BASELINE_RATIO = 0.18  # the baseline sits this share of the size above the line
BASELINE_MIN = 1.5  # ... and at least this many points above it

Rect = Sequence[float]  # x0, y0, x1, y1 in PDF points


def place_size(text_size: float | None, rect: Rect) -> float:
    """The size a place's value is drawn at before fitting: the agreement's text beside it, or a
    share of the box's height."""
    if text_size is not None:
        return text_size
    return min(FALLBACK_CAP, (rect[3] - rect[1]) * FALLBACK_RATIO)


def fitted_size(text: str, rect: Rect, size: float, font_id: str) -> float | None:
    """The size the value is drawn at in this box: ``size`` if it fits the box's width, smaller if
    it must, ``None`` when even ``MIN_SIZE`` is too wide. Only width refuses: a short box's own
    size may be under ``MIN_SIZE``, and a value that fits at it is drawn at it. O(len(text))."""
    width = rect[2] - rect[0]
    per_point = metrics(font_id).text_length(text, fontsize=1)
    if per_point <= 0:
        return size
    fitted = min(size, width / per_point)
    return fitted if fitted >= min(size, MIN_SIZE) else None


def baseline(rect: Rect, size: float) -> float:
    """Where the value's baseline sits: just above the box's bottom edge, its line."""
    return rect[3] - max(BASELINE_MIN, size * BASELINE_RATIO)
