"""Whether a PDF page is a scan: one rule for every module that asks (Phase 4 §3.1, Phase 5c).

Processing records which pages are scans; detection reads those pages from their pictures. Both ask
here, so a page is a scan to both or to neither (a scan with a fax header line is a scan to both).
Pure: a PyMuPDF page in, a yes or no out.
"""

from __future__ import annotations

import pymupdf

# A page is a scan when an image covers at least this share of it and it has fewer than
# MIN_TEXT_CHARACTERS of extractable text. Pages that are blank, or carry only a little text and
# lines (a signature block), are not scans.
MIN_TEXT_CHARACTERS = 20
SCAN_IMAGE_SHARE = 1 / 3


def is_scanned_page(page: pymupdf.Page) -> bool:
    if len("".join(page.get_text("text").split())) >= MIN_TEXT_CHARACTERS:
        return False
    page_area = abs(page.rect.width * page.rect.height) or 1.0
    for image in page.get_image_info():
        x0, y0, x1, y1 = image["bbox"]
        if abs((x1 - x0) * (y1 - y0)) / page_area >= SCAN_IMAGE_SHARE:
            return True
    return False
