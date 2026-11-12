"""Scanned pages as the AI sees them (Phase 5c, `05c-scanned-documents.md`): each page that is a
picture, with each of its fields' ids drawn as a small tag at the start of its line (numbered
marks, ADR-S1). The AI answers per id, as for any field: it never gives these places' positions.

A tag sits in the blank's own box, on the empty row above its line (the scan was read to be empty
there), so it covers no printed words.
"""

from __future__ import annotations

import base64
from typing import Any

import pymupdf

from signora.modules.detection.geometry import unrotated
from signora.modules.detection.reading import Reading

IMAGE_DPI = 120  # a Letter page is about 1,000 by 1,300 pixels: the words stay readable
TAG_SIZE = 7.0  # points of the tag's text
TAG_FILL = (0.85, 0.1, 0.1)


def marked_pages(document: pymupdf.Document, reading: Reading) -> list[dict[str, Any]]:
    """The message parts for the scanned pages: for each, a line saying which page it is and
    its picture with the ids drawn on it. None when the document has no scanned page."""
    parts: list[dict[str, Any]] = []
    for number in reading.scanned_pages:
        copy = pymupdf.open()
        copy.insert_pdf(document, from_page=number - 1, to_page=number - 1)
        page = copy[0]
        for field in reading.asked:
            for placement in field.placements:
                if placement.page == number:
                    _tag(page, field.id, unrotated(page, placement.rect))
        png = page.get_pixmap(dpi=IMAGE_DPI).tobytes("png")
        parts += [
            {"type": "text", "text": f"Page {number}, a scanned picture, its fields tagged:"},
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(png).decode(),
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
