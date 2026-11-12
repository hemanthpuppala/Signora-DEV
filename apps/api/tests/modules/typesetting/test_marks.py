"""Where a signature is drawn: grown to a readable height, never over the agreement's text above
it (typesetting.marks)."""

from __future__ import annotations

import uuid

import pymupdf

from signora.modules.typesetting import SIGNATURE_MIN_HEIGHT, mark_top, mark_tops
from signora.modules.typesetting.sizes import Measured


def _pdf() -> tuple[bytes, float]:
    """A firm's signature block as in a real agreement: its name on the line above the line to
    sign on, a label to the left. Returns the PDF and the heading's bottom."""
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 400), "HARBOR POINT ADVISORY GROUP, LLC", fontsize=11)
    page.insert_text((72, 420), "By (signature): ______________________", fontsize=10)
    page.insert_text((72, 600), "Signature: ______________________", fontsize=10)
    heading_bottom = max(w[3] for w in page.get_text("words") if w[4] == "LLC")
    data: bytes = document.tobytes()
    return data, heading_bottom


def test_a_signature_grows_up_to_just_under_the_text_above_it_and_no_further() -> None:
    pdf, heading_bottom = _pdf()
    under_heading, bare, tall, elsewhere = (uuid.uuid4() for _ in range(4))
    tops = mark_tops(
        pdf,
        [
            Measured(under_heading, 1, (150, 410, 330, 422)),  # the firm's line: heading above
            Measured(bare, 1, (125, 590, 300, 602)),  # nothing above it within reach
            Measured(tall, 1, (125, 640, 300, 700)),  # already taller than the least height
            Measured(elsewhere, 9, (125, 590, 300, 602)),  # no such page: not measured
        ],
    )

    assert heading_bottom < tops[under_heading] <= heading_bottom + 2  # stops under the heading
    assert tops[bare] == 602 - SIGNATURE_MIN_HEIGHT  # the full readable height
    assert tops[tall] == 640  # a tall place is drawn as it is
    assert elsewhere not in tops


def test_words_beside_the_place_or_on_its_own_line_are_not_in_the_way() -> None:
    pdf, _ = _pdf()
    beside = uuid.uuid4()
    # The "Signature:" label is on the place's line, left of it; nothing is above it.
    (top,) = mark_tops(pdf, [Measured(beside, 1, (125, 590, 300, 602))]).values()
    assert top == 602 - SIGNATURE_MIN_HEIGHT


def test_without_a_measurement_the_full_height_is_used_and_a_tall_box_is_kept() -> None:
    assert mark_top((0, 590, 100, 602), None) == 602 - SIGNATURE_MIN_HEIGHT
    assert mark_top((0, 590, 100, 602), 580.0) == 580.0  # measured room
    assert mark_top((0, 500, 100, 602), None) == 500  # taller than the least height
