"""Scanned pages as the AI sees them (Phase 5c, `05c-scanned-documents.md`): each page that is a
picture, with each of its fields' ids drawn as a small tag at the start of its line (numbered
marks, ADR-S1). The AI answers per id, as for any field: it never gives these places' positions.

The page is first rendered as displayed (its /Rotate applied), and the tags are drawn on that
picture in displayed coordinates, so a turned page's tags sit at each line's start and read upright.
A tag sits in the blank's own box, on the empty row above its line, so it covers no printed words.

Pictures are sent as JPEG (the format of scans) within two hard pixel budgets, one per page and
one for the whole document, so a long scan is sent at a lower resolution, never as an unbounded
request: 1.6 million pixels a page, 100 million in all. The longest upload allowed (200 Letter
pages) is still sent at 72 dpi, its words readable: about 12 MB of JPEG in one request.
"""

from __future__ import annotations

import base64
from typing import Any

import pymupdf

from signora.modules.detection.reading import Reading
from signora.modules.detection.scan_lines import render_dpi

IMAGE_DPI = 120  # a Letter page is about 1,000 by 1,300 pixels: the words stay readable
PAGE_PIXELS = 1_600_000  # the most pixels one page's picture holds
DOCUMENT_PIXELS = 100_000_000  # the most a document's pictures hold together (200 Letter at 72 dpi)
JPEG_QUALITY = 75
TAG_SIZE = 7.0  # points of the tag's text
TAG_FILL = (0.85, 0.1, 0.1)


def picture_dpis(document: pymupdf.Document, numbers: list[int]) -> dict[int, int]:
    """Each scanned page's resolution: its own budget first, then all lowered together so the
    document's pictures fit ``DOCUMENT_PIXELS``, a hard limit. O(P) for P pages."""
    dpis = {n: render_dpi(document.load_page(n - 1), IMAGE_DPI, PAGE_PIXELS) for n in numbers}
    total = sum(
        (dpis[n] / 72) ** 2 * abs(document.load_page(n - 1).rect.get_area()) for n in numbers
    )
    if total > DOCUMENT_PIXELS:
        factor = (DOCUMENT_PIXELS / total) ** 0.5
        dpis = {n: max(int(dpi * factor), 1) for n, dpi in dpis.items()}
    return dpis


def marked_pages(document: pymupdf.Document, reading: Reading) -> list[dict[str, Any]]:
    """The message parts for the scanned pages: for each, a line saying which page it is and
    its picture with the ids drawn on it. None when the document has no scanned page."""
    parts: list[dict[str, Any]] = []
    for number, dpi in picture_dpis(document, reading.scanned_pages).items():
        page = document.load_page(number - 1)
        picture = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)  # as displayed
        with pymupdf.open() as canvas:
            sheet = canvas.new_page(width=page.rect.width, height=page.rect.height)
            sheet.insert_image(sheet.rect, pixmap=picture)
            for field in reading.asked:
                for placement in field.placements:
                    if placement.page == number:
                        _tag(sheet, field.id, placement.rect)  # displayed coordinates
            jpeg = sheet.get_pixmap(dpi=dpi).tobytes("jpg", jpg_quality=JPEG_QUALITY)
        parts += [
            {"type": "text", "text": f"Page {number}, a scanned picture, its fields tagged:"},
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
                    "detail": "high",
                },
            },
        ]
    return parts


def _tag(page: pymupdf.Page, field_id: str, box: tuple[float, float, float, float]) -> None:
    """The id as a small white-on-red tag at the start of the blank's line."""
    width = pymupdf.get_text_length(field_id, fontsize=TAG_SIZE) + 4
    tag = pymupdf.Rect(box[0], box[3] - TAG_SIZE - 5, box[0] + width, box[3] - 2)
    page.draw_rect(tag, color=None, fill=TAG_FILL)
    page.insert_text((tag.x0 + 2, tag.y1 - 2), field_id, fontsize=TAG_SIZE, color=(1, 1, 1))
