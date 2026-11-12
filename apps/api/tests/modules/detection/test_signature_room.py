"""The room to sign above a signature place of an approved version, by detection's own rule
(``detection.signature_tops``): never over the page's text, another field, or a scan's ink."""

from __future__ import annotations

import uuid

import pymupdf

from signora.modules.detection import signature_tops
from signora.modules.detection.writing_space import SIGN_HEIGHT
from signora.modules.review import MarkedPlace


def _words_bottom(page: pymupdf.Page, word: str) -> float:
    return float(max(w[3] for w in page.get_text("words") if w[4] == word))


def test_single_spaced_text_right_above_the_line_stops_the_signature_under_it() -> None:
    """A firm's name set one line above its signature line (12 pt apart): its words reach into
    the line's box and still count as above it, so the signature does not grow over them."""
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 400), "HARBOR POINT ADVISORY GROUP, LLC", fontsize=11)
    page.insert_text((72, 412), "By (signature): ______________________", fontsize=11)
    heading = _words_bottom(page, "LLC")
    line = (150.0, 402.0, 330.0, 414.0)  # the blank's box: the line's text row
    place = MarkedPlace(uuid.uuid4(), 1, line, "blank")

    tops = signature_tops(document.tobytes(), [place], {1: [line]})

    assert heading > line[1]  # single spaced: the name reaches into the line's own box
    assert tops[place.id] == line[1]  # so no room above: never over the name


def test_another_field_above_stops_it_and_a_bare_line_grows_to_full_height() -> None:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 100), "CLIENT SERVICES AGREEMENT", fontsize=12)  # a page of text
    title = (150.0, 380.0, 330.0, 394.0)  # another field's place (a title) on the row above
    under_title = MarkedPlace(uuid.uuid4(), 1, (150.0, 402.0, 330.0, 414.0), "blank")
    bare = MarkedPlace(uuid.uuid4(), 1, (150.0, 602.0, 330.0, 614.0), "blank")

    tops = signature_tops(
        document.tobytes(), [under_title, bare], {1: [title, under_title.rect, bare.rect]}
    )

    assert title[3] < tops[under_title.id] < under_title.rect[1]  # just under the title
    assert tops[bare.id] == bare.rect[3] - SIGN_HEIGHT


def test_on_a_scanned_page_the_pictures_ink_above_stops_it() -> None:
    """No words on the page: what is printed above is ink in the picture."""
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.draw_rect(pymupdf.Rect(150, 380, 330, 394), color=(0, 0, 0), fill=(0, 0, 0))
    line = MarkedPlace(uuid.uuid4(), 1, (150.0, 402.0, 330.0, 414.0), "blank")

    tops = signature_tops(document.tobytes(), [line], {1: [line.rect]})

    assert 394 <= tops[line.id] < 402


def test_a_pdf_form_field_and_a_place_beyond_the_last_page_keep_their_own_top() -> None:
    document = pymupdf.open()
    document.new_page(width=612, height=792)
    field = MarkedPlace(uuid.uuid4(), 1, (150.0, 602.0, 330.0, 614.0), "signature")
    missing = MarkedPlace(uuid.uuid4(), 7, (150.0, 602.0, 330.0, 614.0), "blank")

    tops = signature_tops(document.tobytes(), [field, missing], {1: [field.rect]})

    assert tops == {field.id: 602.0, missing.id: 602.0}
