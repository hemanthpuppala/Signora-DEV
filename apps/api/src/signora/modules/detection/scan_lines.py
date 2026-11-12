"""Blank lines on a scanned page, from its pixels (Phase 5c, `05c-scanned-documents.md`).

A scanned page is a picture: no text, no drawings. Its blanks are still lines: an underline, a
signature line, typed underscores that print as one stroke. They are found as a person sees them,
by arithmetic on the page's pixels (no model): a long, thin, dark horizontal stroke. The rules are
F1's (`drawn_lines`), on ink instead of characters:

- a stroke is a blank only where nothing is written on the text row above it (an underlined word
  gives nothing; an underline under "Name:" and the space after it gives the space), and only when
  paper lies under it (the top edge of a line of bold or blurred letters is no line);
- a stroke across most of the page's ink is a rule, and one whose end meets a vertical stroke is a
  table's or a box's border: neither is a blank.

Positions are exact (a pixel at 150 dpi is half a point); the AI only says what each blank holds
(numbered marks, ADR-S1). Each blank also carries the free height above it (``headroom``), the room
a signature may take, since a scan has no words to stop it (F2). Everything is on the page as
displayed (the page is rendered with its rotation). One pass over the page's pixels: O(W·H).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pymupdf

from signora.modules.detection.geometry import Box

SCAN_DPI = 150  # pixels per inch the page is read at: a pixel is about half a point
# The most pixels a page is turned into (a decompression-bomb limit): a Letter or A4 page at
# 150 dpi is about 2.1 million; a larger page is read at a lower resolution, so one page never
# holds more than about 60 MB of arrays however large the PDF says it is.
MAX_PIXELS = 4_200_000
INK_DROP = 45  # a grey this much darker than the page's paper is ink (0 black, 255 white)
INK_DARKEST = 100  # the threshold is never darker than this (a dark, dirty scan) ...
INK_LIGHTEST = 225  # ... nor lighter than this (a faint line on white paper still counts)
SKEW_MAX = 3.0  # degrees a scan may be turned: feeders keep paper within this
SKEW_STEP = 0.1  # degrees between the angles tried
SKEW_SAMPLE = 60_000  # ink points the angle is estimated from (a sample keeps it fast)
SKEW_MIN_INK = 500  # a page with less ink than this is not straightened (nothing to align)
GAP_PX = 2  # pixels: a gap this short inside a stroke is bridged (between printed underscores)
LENGTH_MIN = 20.0  # points: a shorter stroke is a letter's or a dash, not room to write
THICKNESS_MAX = 3.0  # points: a thicker stroke is a bar or a shape, not a line
TEXT_ABOVE = 12.0  # points above a line where what is written on it sits
INK_ABOVE = 2  # dark pixels in a column of that band that make it written (a speck is not)
FULL_WIDTH = 0.8  # a stroke wider than this share of the page's ink is a rule
EDGE_INK = 0.01  # an island of ink at a margin with less than this share of the page's is dust
MARGIN_GAP = 12.0  # points of empty columns that set such an island apart
BORDER = 8.0  # points of vertical ink at a stroke's end that make it a border
HEADROOM_MAX = 36.0  # points: the most room above a line that is measured (F2's height)
MERGE_GAP = 6.0  # points: stretches on one line closer than this are one blank
LINE_FRINGE = 1.0  # points of a line's own rough edge under it, not counted as what is below
PAPER_BELOW = 2.5  # points under a line that are paper: a line is a stroke with paper both sides
INK_BELOW_MAX = 0.3  # a stroke with ink under more of its length is the top edge of text


@dataclass(frozen=True)
class ScanBlank:
    box: Box  # the line with the text row above it, in points, as displayed
    headroom: float  # free points above the line, up to HEADROOM_MAX


def _strokes(ink: np.ndarray, min_px: int, max_px: int) -> list[tuple[int, int, int, int]]:
    """Long horizontal runs of ink, joined into strokes: (x0, x1, y0, y1). Gaps of up to
    ``GAP_PX`` within a row are bridged (printed underscores leave a pixel between them), and
    runs that overlap side by side on touching rows are one stroke, so a line is one stroke."""
    bridged = _close_rows(ink, GAP_PX)
    padded = np.pad(bridged, ((0, 0), (1, 1)), constant_values=False).astype(np.int8)
    edges = np.diff(padded, axis=1)
    rows_on, cols_on = np.nonzero(edges == 1)
    _, cols_off = np.nonzero(edges == -1)
    open_strokes: list[list[int]] = []  # [x0, x1, y0, y1] that the next row may continue
    done: list[list[int]] = []
    for row, x0, x1 in zip(rows_on.tolist(), cols_on.tolist(), cols_off.tolist(), strict=True):
        if x1 - x0 < min_px:
            continue
        done += [s for s in open_strokes if s[3] < row - 1]  # rows ascending: these are closed
        open_strokes = [s for s in open_strokes if s[3] >= row - 1]
        joined = [s for s in open_strokes if min(s[1], x1) > max(s[0], x0)]
        for stroke in joined:
            open_strokes.remove(stroke)
        x0 = min([x0, *(s[0] for s in joined)])
        x1 = max([x1, *(s[1] for s in joined)])
        y0 = min([row, *(s[2] for s in joined)])
        open_strokes.append([x0, x1, y0, row])
    return [(a, b, c, d) for a, b, c, d in done + open_strokes if d - c + 1 <= max_px]


def _close_rows(ink: np.ndarray, gap: int) -> np.ndarray:
    """Horizontal closing (dilate, then erode, by ``(gap + 1) // 2`` pixels each way): a gap of up
    to ``gap`` pixels between ink on one row becomes ink; ink keeps its ends. O(W·H·gap)."""
    reach = (gap + 1) // 2
    grown = ink.copy()
    for shift in range(1, reach + 1):
        grown[:, shift:] |= ink[:, :-shift]
        grown[:, :-shift] |= ink[:, shift:]
    closed = grown.copy()
    for shift in range(1, reach + 1):
        closed[:, shift:] &= grown[:, :-shift]
        closed[:, :-shift] &= grown[:, shift:]
        closed[:, :shift] = False  # nothing beyond the page's edge holds it open
        closed[:, -shift:] = False
    result: np.ndarray = closed | ink  # ink itself is kept, at the page's edges too
    return result


def _border(ink: np.ndarray, x: int, y0: int, y1: int, reach: int) -> bool:
    """Whether a vertical stroke stands at column ``x`` around the rows of a line."""
    top, bottom = max(y0 - reach, 0), min(y1 + reach + 1, ink.shape[0])
    columns = ink[top:bottom, max(x - 2, 0) : x + 3]
    if columns.size == 0:
        return False
    best = 0
    for column in columns.T:
        run = longest = 0
        for value in column:
            run = run + 1 if value else 0
            longest = max(longest, run)
        best = max(best, longest)
    return best >= reach


def scan_blanks(page: pymupdf.Page) -> list[ScanBlank]:
    """The page's blank lines, read from its pixels: the page straightened first (a scanner
    feeds paper at a slight angle), lines found on the straight page, their boxes turned back."""
    dpi = render_dpi(page, SCAN_DPI)
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[
        :, : pix.width
    ]
    raw = _ink(grey)
    angle = _skew(raw)
    ink = _turned(raw, angle) if angle else raw
    scale = dpi / 72  # pixels per point

    def px(points: float) -> int:
        return round(points * scale)

    def back(x: float, y: float) -> tuple[float, float]:
        """A point of the straightened page on the page as scanned, in points."""
        bx, by = _turn_point(x, y, -angle, ink.shape) if angle else (x, y)
        return bx / scale, by / scale

    ink_width = _ink_width(ink, px(MARGIN_GAP))
    blanks: list[ScanBlank] = []
    for x0, x1, y0, y1 in _strokes(ink, px(LENGTH_MIN), px(THICKNESS_MAX)):
        if x1 - x0 > FULL_WIDTH * ink_width:
            continue  # a rule across the page
        if _border(ink, x0, y0, y1, px(BORDER)) or _border(ink, x1 - 1, y0, y1, px(BORDER)):
            continue  # a table's or a box's border
        below = y1 + 1 + px(LINE_FRINGE)  # past the line's own rough edge (blur, straightening)
        under = ink[below : below + px(PAPER_BELOW), x0:x1]
        if under.size and under.any(axis=0).mean() > INK_BELOW_MAX:
            continue  # letters under it: the top edge of a line of (bold or blurred) text
        band = ink[max(y0 - px(TEXT_ABOVE), 0) : max(y0 - 1, 0), x0:x1]
        written = band.sum(axis=0) >= INK_ABOVE if band.size else np.zeros(x1 - x0, dtype=bool)
        for start, end in _free_stretches(written, px(LENGTH_MIN)):
            above = ink[max(y0 - px(HEADROOM_MAX), 0) : max(y0 - 1, 0), x0 + start : x0 + end]
            rows = np.nonzero(above.sum(axis=1) >= INK_ABOVE)[0]
            free_px = (above.shape[0] - 1 - rows[-1]) if rows.size else above.shape[0]
            # The line's own box (its stretch and its rows), turned back onto the scanned page.
            corners = [back(x, y) for x in (x0 + start, x0 + end) for y in (y0, y1 + 1)]
            xs, ys = [c[0] for c in corners], [c[1] for c in corners]
            blanks.append(
                ScanBlank(
                    box=(
                        round(min(xs), 1),
                        round(min(ys) - TEXT_ABOVE, 1),
                        round(max(xs), 1),
                        round(max(ys), 1),
                    ),
                    headroom=round(min(free_px / scale, HEADROOM_MAX), 1),
                )
            )
    return _merge(blanks)


def free_above(page: pymupdf.Page, box: Box, reach: float) -> float:
    """The free height above a box's foot on a scanned page, up to ``reach`` points: the rows
    above it, across its width, with nothing written in them (a place with no line, which the
    AI gave by its box; F2's room to sign). Only that strip is rendered: O(width · reach)."""
    x0, _, x1, y1 = box
    clip = pymupdf.Rect(x0, max(y1 - reach, 0), x1, y1) & page.rect  # as displayed
    if clip.is_empty:
        return 0.0
    pix = page.get_pixmap(dpi=SCAN_DPI, clip=clip, colorspace=pymupdf.csGRAY)
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[
        :, : pix.width
    ]
    rows = np.nonzero(_ink(grey).sum(axis=1) >= INK_ABOVE)[0]
    height = int(pix.height)
    free_px = height - 1 - int(rows[-1]) if rows.size else height
    return round(min(free_px * float(clip.height) / max(height, 1), reach), 1)


def _ink_width(ink: np.ndarray, gap_px: int) -> int:
    """How wide the page's ink runs, in pixels, without dust: the ink's columns fall into islands
    split by ``gap_px`` or more of empty columns, and an island at either edge with under
    ``EDGE_INK`` of the page's ink is a speck in a margin, not the page (counted, it would widen
    the page and let a rule pass as a blank). One pass over the columns: O(W·H)."""
    mass = ink.sum(axis=0)
    columns = np.nonzero(mass)[0]
    if columns.size == 0:
        return int(ink.shape[1])
    breaks = np.nonzero(np.diff(columns) > gap_px)[0]
    starts = np.concatenate(([columns[0]], columns[breaks + 1]))
    ends = np.concatenate((columns[breaks], [columns[-1]]))
    sizes = [int(mass[a : b + 1].sum()) for a, b in zip(starts, ends, strict=True)]
    least = EDGE_INK * sum(sizes)
    first, last = 0, len(sizes) - 1
    while first < last and sizes[first] < least:
        first += 1
    while last > first and sizes[last] < least:
        last -= 1
    return max(int(ends[last] - starts[first]), 1)


def _ink(grey: np.ndarray) -> np.ndarray:
    """What is ink on the page: darker than its paper by ``INK_DROP`` (the paper's grey is the
    page's median: most of a page is paper), so a faint, blurred line still counts."""
    paper = float(np.median(grey))
    threshold = min(max(paper - INK_DROP, INK_DARKEST), INK_LIGHTEST)
    ink: np.ndarray = grey < threshold
    return ink


def _skew(ink: np.ndarray) -> float:
    """The angle, in degrees, that straightens the page: of the angles within ``SKEW_MAX``, the
    one at which the ink's rows line up most sharply (the squared row counts are largest), the
    standard projection-profile estimate. 0 when the page is straight or nearly empty. O(N·A)
    for N sampled ink points and A angles."""
    ys, xs = np.nonzero(ink)
    if xs.size < SKEW_MIN_INK:
        return 0.0
    step = max(xs.size // SKEW_SAMPLE, 1)
    ys, xs = ys[::step].astype(np.float64), xs[::step].astype(np.float64)
    cy, cx = ink.shape[0] / 2, ink.shape[1] / 2
    best, best_score = 0.0, -1.0
    for angle in np.arange(-SKEW_MAX, SKEW_MAX + SKEW_STEP / 2, SKEW_STEP):
        theta = np.radians(angle)
        rows = (xs - cx) * np.sin(theta) + (ys - cy) * np.cos(theta)
        counts = np.bincount((rows - rows.min()).astype(np.int64))
        score = float((counts.astype(np.float64) ** 2).sum())
        if score > best_score:
            best, best_score = float(angle), score
    return best if abs(best) >= SKEW_STEP / 2 else 0.0


def _turn_point(x: float, y: float, angle: float, shape: tuple[int, ...]) -> tuple[float, float]:
    """A point turned by ``angle`` degrees about the page's centre (the straightening's map)."""
    cy, cx = shape[0] / 2, shape[1] / 2
    theta = np.radians(angle)
    c, s = float(np.cos(theta)), float(np.sin(theta))
    return cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c


def _turned(ink: np.ndarray, angle: float) -> np.ndarray:
    """The ink turned by ``angle`` about the page's centre (its points moved, rounded to pixels;
    the closing in ``_strokes`` mends the pin-holes rounding leaves in a line)."""
    ys, xs = np.nonzero(ink)
    cy, cx = ink.shape[0] / 2, ink.shape[1] / 2
    theta = np.radians(angle)
    c, s = np.cos(theta), np.sin(theta)
    tx = np.rint(cx + (xs - cx) * c - (ys - cy) * s).astype(np.int64)
    ty = np.rint(cy + (xs - cx) * s + (ys - cy) * c).astype(np.int64)
    keep = (tx >= 0) & (tx < ink.shape[1]) & (ty >= 0) & (ty < ink.shape[0])
    turned = np.zeros_like(ink)
    turned[ty[keep], tx[keep]] = True
    return turned


def _free_stretches(written: np.ndarray, min_px: int) -> list[tuple[int, int]]:
    """The runs of columns with nothing written, at least ``min_px`` wide: (start, end)."""
    stretches: list[tuple[int, int]] = []
    start = None
    for index, taken in enumerate([*written.tolist(), True]):
        if not taken and start is None:
            start = index
        elif taken and start is not None:
            if index - start >= min_px:
                stretches.append((start, index))
            start = None
    return stretches


def _merge(blanks: list[ScanBlank]) -> list[ScanBlank]:
    """Stretches of one line closer than ``MERGE_GAP`` side by side are one blank. Rows first
    (feet within a point), then left to right: two blanks of a row that are apart stay apart."""
    rows: list[list[ScanBlank]] = []
    for blank in sorted(blanks, key=lambda b: b.box[3]):
        if rows and blank.box[3] - rows[-1][0].box[3] < 1:
            rows[-1].append(blank)
        else:
            rows.append([blank])
    merged: list[ScanBlank] = []
    for row in rows:
        current: ScanBlank | None = None
        for blank in sorted(row, key=lambda b: b.box[0]):
            if current is not None and blank.box[0] - current.box[2] < MERGE_GAP:
                box = (
                    current.box[0],
                    min(current.box[1], blank.box[1]),
                    max(current.box[2], blank.box[2]),
                    max(current.box[3], blank.box[3]),
                )
                current = ScanBlank(box=box, headroom=min(current.headroom, blank.headroom))
            else:
                if current is not None:
                    merged.append(current)
                current = blank
        if current is not None:
            merged.append(current)
    return merged


def render_dpi(page: pymupdf.Page, wanted: float, max_pixels: int = MAX_PIXELS) -> int:
    """The resolution a page is turned into pixels at: ``wanted``, lowered so the picture holds
    at most ``max_pixels``. O(1)."""
    area = max(page.rect.width * page.rect.height, 1.0)  # square points, as displayed
    fits = 72 * (max_pixels / area) ** 0.5
    return max(int(min(wanted, fits)), 1)
