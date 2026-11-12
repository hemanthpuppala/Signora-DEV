"""The room to sign above each signature or initials place of an approved version, by detection's
own rule (findings F2, ``writing_space.PageSpace.room_above`` and ``scan_lines.free_above``).

Detection grows a signature line's box into the free space above it when it finds the field. A
version detected before that rule, or whose box was drawn short in review, is measured once at
approval (and older approved versions by ``signora measure-text-sizes``), with the same rule and
nothing else: the page's visible words and the version's other places stop it; on a page with no
words (a scan) the picture's free height above the line does; a PDF's own form field is drawn as
its author drew it. Review asks through ``review.provide_signature_room``: review cannot import
detection, which imports review.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

import pymupdf

from signora.modules.detection.derive import grown_from_foot
from signora.modules.detection.geometry import Box
from signora.modules.detection.scan_lines import free_above
from signora.modules.detection.writing_space import SIGN_HEIGHT, DocumentSpace, visible
from signora.modules.review import MarkedPlace
from signora.modules.typesetting.mupdf import MUPDF_LOCK


def signature_tops(
    pdf: bytes, places: Sequence[MarkedPlace], others: Mapping[int, Sequence[Box]]
) -> dict[uuid.UUID, float]:
    """Each place's top: grown into the free space above its line, never smaller than it was.
    ``others``: every place of the version by page (the obstacles; a place never stops itself).
    A place on a page the document does not have keeps its own top. O(W + P) per page for W words
    and P places, plus a strip of pixels per place on a scanned page."""
    tops: dict[uuid.UUID, float] = {}
    with MUPDF_LOCK, pymupdf.open(stream=pdf, filetype="pdf") as document:
        space = DocumentSpace(document, {page: list(boxes) for page, boxes in others.items()})
        scanned: dict[int, bool] = {}
        for place in places:
            rect: Box = place.rect
            page_space = space.page(place.page)
            if place.kind != "blank" or page_space is None:
                tops[place.id] = rect[1]  # a form field as its author drew it; or no such page
                continue
            if place.page not in scanned:
                page = document.load_page(place.page - 1)
                scanned[place.page] = not any(visible(word[4]) for word in page.get_text("words"))
            if scanned[place.page]:
                found = free_above(document.load_page(place.page - 1), rect, SIGN_HEIGHT)
                tops[place.id] = grown_from_foot(rect, found)[1]
            else:
                tops[place.id] = page_space.room_above(rect)[1]
    return tops
