"""The read stage (LLD §1.2, topic 2): from a PDF's bytes to its numbered fields and layout text."""

from __future__ import annotations

import pymupdf

from signora.modules.detection import blanks, form_fields, layout
from signora.modules.detection.page_text import pages
from signora.modules.detection.reading import (
    FieldsFrom,
    FoundField,
    PageInfo,
    Placement,
    Reading,
    number_fields,
)
from signora.modules.detection.scan_lines import is_image_page, scan_blanks


def read_document(data: bytes) -> Reading:
    """Form fields and the blanks no form field covers, numbered in reading order, with the layout
    text. Pure: no database, no files; about 45 ms a page."""
    with pymupdf.open(stream=data, filetype="pdf") as document:
        form = form_fields.read_form(document)
        found = blanks.find_blanks(document, covered=form.boxes_by_page)
        scanned = [number for number, page in pages(document) if is_image_page(page)]
        found += _scanned_blanks(document, scanned)
        fields = number_fields(form.fields + found)
        infos = [
            PageInfo(
                number=number,
                width=round(page.rect.width, 1),
                height=round(page.rect.height, 1),
                rotation=page.rotation,
            )
            for number, page in pages(document)
        ]
        for field in fields:
            field.issues = form_fields.issues(field, infos)
        fields_from: FieldsFrom = "form_fields" if form.fields else "blanks" if found else "none"
        reading = Reading(
            fields_from=fields_from,
            fields=fields,
            pages=infos,
            xfa=form.xfa,
            already_signed=any(field.signed for field in fields),
            scanned_pages=scanned,
        )
        reading.layout = layout.layout_text(document, reading)
    return reading


def _scanned_blanks(document: pymupdf.Document, numbers: list[int]) -> list[FoundField]:
    """The lines of the pages that are pictures (Phase 5c): found from their pixels, at exact
    positions, with no words to label them (the AI names them from the page's picture). They are
    the least certain mark, as drawn lines are (``drawn``)."""
    found: list[FoundField] = []
    for number in numbers:
        for index, blank in enumerate(scan_blanks(document.load_page(number - 1))):
            found.append(
                FoundField(
                    ref=f"scan:{number}:{index}",
                    kind="blank",
                    placements=[Placement(page=number, rect=blank.box, headroom=blank.headroom)],
                    drawn=True,
                )
            )
    return found
