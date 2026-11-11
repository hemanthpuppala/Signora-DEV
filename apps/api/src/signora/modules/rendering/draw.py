"""Writing values and signatures into a PDF's pages (Phase 8 LLD §10). Pure apart from the PDF
library: bytes in, bytes out.

The original's pages are kept; each value becomes page content (not a form field), drawn by
typesetting's own rules (the same as the browser's preview), and the original's form fields,
annotations, links and scripts are removed, so nothing in the result can be edited or run. Every
page carries the envelope's ID in its top margin. O(pages + places + stroke points).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf

from signora.modules.typesetting.fit import baseline, fitted_size, left_edge
from signora.modules.typesetting.fonts import font_path
from signora.modules.typesetting.mupdf import MUPDF_LOCK

Rect = tuple[float, float, float, float]  # PDF points on the page as displayed

PAD_WIDTH, PAD_HEIGHT = 1000, 400  # a drawn signature's own box (signing.signatures)
FRAME_MIN_HEIGHT = 24.0  # a box shorter than this gets the signature without its frame
# A signature is at least this tall, standing on its line: a box found on a signature line is
# often only the line's own height, and a signature squeezed into it cannot be read. The web
# draws it the same way (shared/document/SignatureMark: SIGNATURE_MIN_HEIGHT).
SIGNATURE_MIN_HEIGHT = 36.0
INK = (0.1, 0.1, 0.1)
QUIET = (0.45, 0.45, 0.45)
FRAME = (0.2, 0.35, 0.6)


@dataclass(frozen=True)
class Text:
    page: int  # 1-based
    rect: Rect
    text: str
    size: float  # the size before fitting: the agreement's text size, or the box's share
    font: str  # a typesetting font id


@dataclass(frozen=True)
class Mark:
    """A tick: a ticked checkbox, or the chosen option's place."""

    page: int
    rect: Rect


@dataclass(frozen=True)
class TypedSignature:
    page: int
    rect: Rect
    text: str
    font: str  # a handwriting font id
    signature_id: str  # the first 16 hexadecimal characters of its fingerprint
    initials: bool = False


@dataclass(frozen=True)
class DrawnSignature:
    page: int
    rect: Rect
    strokes: Sequence[Sequence[tuple[int, int]]]
    signature_id: str
    initials: bool = False


Item = Text | Mark | TypedSignature | DrawnSignature


class _Page:
    """One page, drawn in the page's displayed coordinates (rotation applied)."""

    def __init__(self, page: pymupdf.Page) -> None:
        self.page = page
        self.fonts: dict[str, str] = {}
        self.to_page = page.derotation_matrix  # displayed -> the page's own coordinates

    def font(self, font_id: str) -> str:
        if font_id not in self.fonts:
            name = f"F{len(self.fonts)}"
            self.page.insert_font(fontname=name, fontfile=str(font_path(font_id)))
            self.fonts[font_id] = name
        return self.fonts[font_id]

    def point(self, x: float, y: float) -> pymupdf.Point:
        moved: pymupdf.Point = pymupdf.Point(x, y) * self.to_page
        return moved

    def text(
        self,
        x: float,
        y: float,
        words: str,
        size: float,
        font_id: str,
        color: tuple[float, float, float] = INK,
    ) -> None:
        self.page.insert_text(
            self.point(x, y),
            words,
            fontsize=size,
            fontname=self.font(font_id),
            color=color,
            rotate=self.page.rotation,
        )

    def line(
        self,
        a: tuple[float, float],
        b: tuple[float, float],
        width: float,
        color: tuple[float, float, float] = INK,
    ) -> None:
        self.page.draw_line(self.point(*a), self.point(*b), color=color, width=width, lineCap=1)

    def polyline(self, points: Sequence[tuple[float, float]], width: float) -> None:
        self.page.draw_polyline(
            [self.point(x, y) for x, y in points], color=INK, width=width, lineCap=1, lineJoin=1
        )


def _text(page: _Page, item: Text) -> None:
    size = fitted_size(item.text, item.rect, item.size, item.font)
    if size is None:  # refused at its box and at submit; never reached here
        size = item.size
    x = left_edge(item.rect, item.text, size, item.font)
    page.text(x, baseline(item.rect, size), item.text, size, item.font)


def _mark(page: _Page, item: Mark) -> None:
    x0, y0, x1, y1 = item.rect
    side = min(x1 - x0, y1 - y0) * 0.7
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    width = max(0.8, side / 8)
    page.line((cx - side / 2, cy), (cx - side / 8, cy + side / 2.5), width)
    page.line((cx - side / 8, cy + side / 2.5), (cx + side / 2, cy - side / 2.2), width)


def _inner(rect: Rect, framed: bool) -> Rect:
    """Where a signature itself goes: inside its frame's words when it has a frame."""
    x0, y0, x1, y1 = rect
    if not framed:
        return rect
    height = y1 - y0
    return (x0 + 6, y0 + height * 0.22, x1 - 2, y1 - height * 0.22)


def _frame(page: _Page, rect: Rect, signature_id: str, initials: bool) -> None:
    """The Signed by frame (§10.1.4): a bracket, "Signed by:" above, the signature's ID below."""
    x0, y0, _, y1 = rect
    height = y1 - y0
    small = max(4.5, min(7.0, height * 0.16))
    page.line((x0 + 2, y0 + 2), (x0 + 2, y1 - 2), 0.6, FRAME)
    page.line((x0 + 2, y0 + 2), (x0 + 12, y0 + 2), 0.6, FRAME)
    page.line((x0 + 2, y1 - 2), (x0 + 12, y1 - 2), 0.6, FRAME)
    if not initials:
        page.text(x0 + 6, y0 + 2 + small, "Signed by:", small, "liberation-sans", FRAME)
    page.text(x0 + 6, y1 - 3, signature_id.upper(), small, "liberation-sans", QUIET)


def signature_box(rect: Rect) -> Rect:
    """Where a signature goes: its box, grown upwards from its line to the least readable height."""
    x0, y0, x1, y1 = rect
    return (x0, min(y0, y1 - SIGNATURE_MIN_HEIGHT), x1, y1)


def _typed(page: _Page, item: TypedSignature) -> None:
    rect = signature_box(item.rect)
    framed = rect[3] - rect[1] >= FRAME_MIN_HEIGHT
    inner = _inner(rect, framed)
    size = (inner[3] - inner[1]) * 0.85
    fitted = fitted_size(item.text, inner, size, item.font) or size
    page.text(
        left_edge(inner, item.text, fitted, item.font),
        inner[3] - fitted * 0.18,
        item.text,
        fitted,
        item.font,
    )
    if framed:
        _frame(page, rect, item.signature_id, item.initials)


def _drawn(page: _Page, item: DrawnSignature) -> None:
    rect = signature_box(item.rect)
    framed = rect[3] - rect[1] >= FRAME_MIN_HEIGHT
    x0, y0, x1, y1 = _inner(rect, framed)
    scale = min((x1 - x0) / PAD_WIDTH, (y1 - y0) / PAD_HEIGHT)
    dx = x0 + ((x1 - x0) - PAD_WIDTH * scale) / 2
    dy = y0 + ((y1 - y0) - PAD_HEIGHT * scale) / 2
    width = max(0.6, 6 * scale)
    for stroke in item.strokes:
        points = [(dx + x * scale, dy + y * scale) for x, y in stroke]
        if len(points) == 1:
            points.append((points[0][0] + 0.2, points[0][1]))
        page.polyline(points, width)
    if framed:
        _frame(page, rect, item.signature_id, item.initials)


def _flatten(doc: pymupdf.Document) -> None:
    """Remove what could be edited or run: form fields, annotations, links, scripts, actions."""
    for index in range(doc.page_count):
        page = doc[index]
        for widget in list(page.widgets() or []):
            page.delete_widget(widget)
        for annot in list(page.annots() or []):
            page.delete_annot(annot)
        for link in page.get_links():
            page.delete_link(link)
    catalog = doc.pdf_catalog()
    for key in ("AcroForm", "OpenAction", "AA", "Names"):
        doc.xref_set_key(catalog, key, "null")


def render(pdf: bytes, items: Sequence[Item], *, envelope_id: uuid.UUID) -> bytes:
    """The original's pages with every item written in, flattened, the envelope's ID on each
    page. The fonts are embedded with only the letters used."""
    with MUPDF_LOCK:
        doc = pymupdf.open(stream=pdf, filetype="pdf")
        try:
            _flatten(doc)
            pages = [_Page(doc[index]) for index in range(doc.page_count)]
            stamp = f"Signora envelope ID: {str(envelope_id).upper()}"
            for page in pages:
                page.text(18, 12, stamp, 7, "liberation-sans", QUIET)
            for item in items:
                page = pages[item.page - 1]
                if isinstance(item, Text):
                    _text(page, item)
                elif isinstance(item, Mark):
                    _mark(page, item)
                elif isinstance(item, TypedSignature):
                    _typed(page, item)
                else:
                    _drawn(page, item)
            doc.subset_fonts()
            out: bytes = doc.tobytes(garbage=3, deflate=True)
            return out
        finally:
            doc.close()


def combine(*pdfs: bytes) -> bytes:
    """PDFs one after another in one file (the document, then its certificate)."""
    with MUPDF_LOCK:
        out = pymupdf.open()
        try:
            for data in pdfs:
                part = pymupdf.open(stream=data, filetype="pdf")
                try:
                    out.insert_pdf(part)
                finally:
                    part.close()
            joined: bytes = out.tobytes(garbage=3, deflate=True)
            return joined
        finally:
            out.close()
