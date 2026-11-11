"""Room to sign on a line (findings F2): a signature or initials on a blank line takes the writing
space above it; a form field's box and every other value keep their size."""

from __future__ import annotations

from typing import Any

import pymupdf
import pytest

from signora.modules.detection.derive import derive
from signora.modules.detection.geometry import Box
from signora.modules.detection.read import read_document
from signora.modules.detection.writing_space import CLEARANCE, SIGN_HEIGHT, visible

LINE = "_" * 30


def _flat(texts: list[tuple[float, float, str]], rotation: int = 0) -> bytes:
    """A flat page with text at (x, baseline y): blanks are typed underscores."""
    document = pymupdf.open()
    page = document.new_page()
    for x, y, text in texts:
        page.insert_text((x, y), text, fontsize=11)
    page.set_rotation(rotation)
    data: bytes = document.tobytes()
    return data


def _read(data: bytes) -> list[Box]:
    """Each asked field's first place as read, in reading order (f1, f2, …)."""
    return [found.placements[0].rect for found in read_document(data).asked]


def _derive(data: bytes, holds: list[str]) -> dict[Box, Box]:
    """The fields answered in reading order as ``holds`` says, filled by the one signer; each
    place's box as read -> as derived (places keep their reading order within a field)."""
    reading = read_document(data)
    fields = [
        {
            "id": found.id,
            "holds": holds[n],
            "format": None,
            "filled_by": "client",
            "label": f"Field {n + 1}",
            "must_fill": True,
            "depends_on": None,
        }
        for n, found in enumerate(reading.asked)
    ]
    answer: dict[str, Any] = {
        "roles": [{"slug": "client", "kind": "signer"}],
        "fields": fields,
        "checkbox_groups": [],
        "extra_fields": [],
        "document": None,
    }
    with pymupdf.open(stream=data, filetype="pdf") as document:
        result = derive(reading, answer, document, problems=[], repaired=False)
    derived = sorted(
        (place.rect for field in result.fields for place in field.placements), key=lambda r: r[3]
    )
    read = sorted(_read(data), key=lambda r: r[3])
    return dict(zip(read, derived, strict=True))


def test_a_signature_line_takes_the_space_above_it_and_keeps_its_line() -> None:
    data = _flat([(72, 100, "Client's Signature"), (72, 160, LINE)])
    ((before, after),) = _derive(data, ["signature"]).items()
    assert before[3] - before[1] < 16  # one text line, as read
    # The line stays its bottom edge; only the top moves.
    assert (after[0], after[2], after[3]) == (before[0], before[2], before[3])
    assert after[3] - after[1] == SIGN_HEIGHT


def test_it_stops_below_the_words_above_it() -> None:
    data = _flat([(72, 136, "Client's Signature"), (72, 160, LINE)])
    ((before, after),) = _derive(data, ["signature"]).items()
    heading = next(w for w in pymupdf.open(stream=data, filetype="pdf")[0].get_text("words"))
    assert after[1] == pytest.approx(round(heading[3], 1) + CLEARANCE)  # positions in tenths
    assert before[1] > after[1] and after[3] - after[1] < SIGN_HEIGHT


def test_it_stops_below_another_field_above_it() -> None:
    """Two signature lines 30 pt apart: the lower one grows only up to the upper one's line."""
    data = _flat([(72, 130, LINE), (72, 160, LINE)])
    upper, lower = sorted(_read(data), key=lambda r: r[1])
    grown = _derive(data, ["signature", "signature"])
    assert grown[lower][1] == pytest.approx(upper[3] + CLEARANCE)
    assert grown[upper][3] - grown[upper][1] == SIGN_HEIGHT


def test_initials_grow_too_and_other_values_keep_their_size() -> None:
    data = _flat([(72, 100, "Initials"), (72, 160, LINE), (300, 100, "Name"), (300, 160, LINE)])
    initials, name = _read(data)  # one row: left to right
    grown = _derive(data, ["initials", "full_name"])
    assert grown[initials][3] - grown[initials][1] == SIGN_HEIGHT
    assert grown[name] == name


def test_a_form_fields_signature_box_keeps_the_size_its_author_drew() -> None:
    """Signing fills that form field: its box is never changed, even when it is short."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 100), "Signature", fontsize=11)
    widget = pymupdf.Widget()
    widget.field_name, widget.field_type = "Sig", pymupdf.PDF_WIDGET_TYPE_SIGNATURE  # type: ignore[attr-defined]
    widget.rect = pymupdf.Rect(72, 150, 272, 162)  # 12 pt: short, with free space above
    page.add_widget(widget)
    ((before, after),) = _derive(document.tobytes(), ["signature"]).items()
    assert after == before


def test_on_a_page_whose_text_is_shown_sideways_the_box_is_kept() -> None:
    """Upright text on a page turned by /Rotate 90 reads sideways as shown: "above the line" is
    not the page's up there, so nothing is guessed."""
    data = _flat([(72, 100, "Signature"), (72, 160, LINE)], rotation=90)
    ((before, after),) = _derive(data, ["signature"]).items()
    assert after == before


def test_spaces_and_invisible_characters_leave_the_space_free() -> None:
    assert not visible("\u200b\u200b")
    assert not visible("\u00ad\u2002\u2002\u200b")
    assert not visible("   ")
    assert visible("Signature")
