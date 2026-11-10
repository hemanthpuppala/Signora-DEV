"""The agreement's text size beside each place, read from the PDF (Phase 7b LLD)."""

from __future__ import annotations

import uuid

import pymupdf

from signora.modules.typesetting.sizes import Measured, text_sizes


def _pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 100), "CONFIDENTIALITY AGREEMENT", fontsize=18)
    page.insert_text((72, 200), "made and entered into as of this", fontsize=11)
    page.insert_text((72, 300), "Print Name", fontsize=9.2)
    data: bytes = document.tobytes()
    return data


def test_a_place_takes_the_size_of_the_words_on_its_row_or_else_the_pages() -> None:
    beside, small, alone, elsewhere = (uuid.uuid4() for _ in range(4))
    sizes = text_sizes(
        _pdf(),
        [
            Measured(beside, 1, (260, 188, 320, 202)),  # "__ day of": on the 11 pt row
            Measured(small, 1, (140, 290, 300, 302)),  # after "Print Name", 9.2 pt: half points
            Measured(alone, 1, (72, 500, 200, 514)),  # nothing on its row: the page's median
            Measured(elsewhere, 9, (72, 500, 200, 514)),  # no such page: not measured
        ],
    )

    assert sizes[beside] == 11.0
    assert sizes[small] == 9.0
    assert sizes[alone] == 11.0
    assert elsewhere not in sizes


def test_text_too_small_to_read_is_not_the_agreements_text() -> None:
    # A scan's hidden text layer on the blank's row: 0.2 pt would round to no size at all, and
    # 1 pt would have values drawn at 1 pt.
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 200), "made and entered into as of this", fontsize=11)
    page.insert_text((72, 300), "hidden layer", fontsize=0.2)
    page.insert_text((72, 400), "hidden layer", fontsize=1)
    tiny, small, body = (uuid.uuid4() for _ in range(3))
    sizes = text_sizes(
        document.tobytes(),
        [
            Measured(tiny, 1, (140, 296, 300, 302)),
            Measured(small, 1, (140, 392, 300, 402)),
            Measured(body, 1, (260, 188, 320, 202)),
        ],
    )

    assert sizes == {tiny: 11.0, small: 11.0, body: 11.0}  # the page's readable text
