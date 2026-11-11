"""Free space to write in (findings F2, F10): a signature or initials on a blank line takes the
writing space above it, a form field's box and every other value keeping their size; a blank the AI
found where the page marks nothing goes in the free space after the words printed before it."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pymupdf
import pytest

from signora.modules.detection.derive import Result, check, derive
from signora.modules.detection.geometry import Box
from signora.modules.detection.read import read_document
from signora.modules.detection.writing_space import (
    CLEARANCE,
    LABEL_GAP,
    MIN_WIDTH,
    SIGN_HEIGHT,
    visible,
)

LINE = "_" * 30


def _flat(texts: Sequence[tuple[float, float, str]], rotation: int = 0) -> bytes:
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


# --- F10: a blank the page marks nothing goes after the words printed before it ------------------

PARAGRAPH = "The parties have executed this Agreement as of the dates written below, in two copies."


def _with_extras(data: bytes, extras: list[dict[str, Any]], holds: list[str]) -> Result:
    """The found blanks answered in reading order as ``holds`` says (left column: party_1, right:
    party_2), and ``extras`` as the AI's extra fields; each extra's other keys default."""
    reading = read_document(data)
    fields = [
        {
            "id": found.id,
            "holds": holds[n],
            "format": None,
            "filled_by": "party_1" if found.placements[0].rect[0] < 300 else "party_2",
            "label": f"Field {n + 1}",
            "must_fill": True,
            "depends_on": None,
        }
        for n, found in enumerate(reading.asked)
    ]
    answer: dict[str, Any] = {
        "roles": [{"slug": "party_1", "kind": "signer"}, {"slug": "party_2", "kind": "signer"}],
        "fields": fields,
        "checkbox_groups": [],
        "extra_fields": [
            {"page": 1, "holds": "full_name", "format": None, "must_fill": True, **extra}
            for extra in extras
        ],
        "document": None,
    }
    with pymupdf.open(stream=data, filetype="pdf") as document:
        return derive(reading, answer, document, problems=[], repaired=False)


def _words(data: bytes, text: str) -> list[pymupdf.Rect]:
    return pymupdf.open(stream=data, filetype="pdf")[0].search_for(text)


def _extra(result: Result, label: str) -> Box:
    return next(f for f in result.fields if f.label == label).placements[0].rect


def test_an_extra_field_goes_in_the_space_after_its_label_on_its_row() -> None:
    data = _flat([(72, 100, PARAGRAPH), (72, 160, "NAME:")])
    (label,) = _words(data, "NAME:")
    result = _with_extras(
        data, [{"anchor_text": "NAME:", "filled_by": "party_1", "label": "Name"}], []
    )
    x0, y0, x1, y1 = _extra(result, "Name")
    assert x0 == pytest.approx(label.x1 + LABEL_GAP, abs=0.1)  # just after the label, not on it
    assert (y0, y1) == pytest.approx((label.y0, label.y1), abs=0.1)  # on its row, one line tall
    assert x1 - x0 >= MIN_WIDTH


def test_of_two_printings_of_its_label_it_takes_the_one_by_its_partys_other_places() -> None:
    """A signature block in two columns, each with "NAME:": each party's name lands in its own
    column, and the left one stops before the right column's label."""
    data = _flat(
        [
            (72, 100, PARAGRAPH),
            (72, 140, "By: " + "_" * 20),
            (324, 140, "By: " + "_" * 20),
            (72, 160, "NAME:"),
            (324, 160, "NAME:"),
        ]
    )
    left, right = sorted(_words(data, "NAME:"), key=lambda r: r.x0)
    result = _with_extras(
        data,
        [
            {"anchor_text": "NAME:", "filled_by": "party_2", "label": "Right name"},
            {"anchor_text": "NAME:", "filled_by": "party_1", "label": "Left name"},
        ],
        ["signature", "signature"],
    )
    right_box, left_box = _extra(result, "Right name"), _extra(result, "Left name")
    assert right_box[0] > right.x1 and left_box[0] > left.x1
    assert left_box[2] <= right.x0 - CLEARANCE  # never runs into the other column


def test_a_label_that_ends_its_line_with_no_room_left_has_its_blank_on_the_line_below() -> None:
    """The words right before the blank end the line, too close to the edge for a box: the blank
    is on the line below, from the label's left edge."""
    line = "Address of the party receiving the information:"
    edge = 72 + pymupdf.get_text_length(PARAGRAPH, fontsize=11)  # the text's right edge
    data = _flat(
        [(72, 100, PARAGRAPH), (edge - pymupdf.get_text_length(line, fontsize=11), 160, line)]
    )
    words = "receiving the information:"
    (label,) = _words(data, words)
    result = _with_extras(
        data, [{"anchor_text": words, "filled_by": "party_1", "label": "Address"}], []
    )
    x0, y0, _, _ = _extra(result, "Address")
    assert x0 == pytest.approx(label.x0, abs=0.1) and y0 >= label.y1


def test_words_printed_after_a_label_are_never_skipped_for_the_line_below() -> None:
    """A value printed after the label means the label's blank is filled, not that it moved."""
    data = _flat([(72, 100, PARAGRAPH), (72, 160, "NAME: Dr. Carolyn Bruder")])
    result = _with_extras(
        data, [{"anchor_text": "NAME:", "filled_by": "party_1", "label": "Name"}], []
    )
    assert result.fields == [] and any("'Name' dropped" in note for note in result.notes)


def test_with_no_free_space_after_its_words_it_is_a_problem_then_dropped() -> None:
    """The repair round asks for the words right before the blank; if they still have no room,
    the field is dropped with a note rather than written over the text."""
    data = _flat(
        [(72, 100, PARAGRAPH), (72, 112, "Each copy is an original, signed on the dates below.")]
    )
    extras = [{"anchor_text": "The parties", "filled_by": "party_1", "label": "Name"}]
    reading = read_document(data)
    answer: dict[str, Any] = {
        "roles": [{"slug": "party_1", "kind": "signer"}],
        "fields": [],
        "checkbox_groups": [],
        "extra_fields": [
            {"page": 1, "holds": "full_name", "format": None, "must_fill": True, **extras[0]}
        ],
        "document": None,
    }
    with pymupdf.open(stream=data, filetype="pdf") as document:
        problems = check(answer, reading, document)
        result = derive(reading, answer, document, problems=problems, repaired=True)
    assert any("no free space after 'The parties'" in problem for problem in problems)
    assert result.fields == [] and any("'Name' dropped" in note for note in result.notes)


def test_a_signature_found_by_the_ai_is_placed_after_its_label_then_given_room_to_sign() -> None:
    """One model of free space for both: the extra signature is placed after "By:", then grows
    into the space above its row like any signature on a line."""
    data = _flat([(72, 100, PARAGRAPH), (72, 160, "By:")])
    (label,) = _words(data, "By:")
    result = _with_extras(
        data,
        [{"anchor_text": "By:", "filled_by": "party_1", "label": "Sign", "holds": "signature"}],
        [],
    )
    x0, y0, _, y1 = _extra(result, "Sign")
    assert x0 > label.x1 and y1 == pytest.approx(label.y1, abs=0.1)
    assert y1 - y0 > label.y1 - label.y0  # taller than its row: room to sign


def test_a_field_never_takes_another_partys_column_when_its_own_is_already_filled_in() -> None:
    """The right column's NAME is printed ("Dr. Carolyn Bruder"). A field the AI wrongly gives it,
    even listed first, is a problem for the repair round and is dropped; it never takes the left
    column's free space, which stays the left party's."""
    data = _flat(
        [
            (72, 100, PARAGRAPH),
            (72, 140, "By: " + "_" * 20),
            (324, 140, "By: " + "_" * 20),
            (72, 160, "NAME:"),
            (324, 160, "NAME: Dr. Carolyn Bruder"),
        ]
    )
    left, _ = sorted(_words(data, "NAME:"), key=lambda r: r.x0)
    reading = read_document(data)
    answer: dict[str, Any] = {
        "roles": [{"slug": "party_1", "kind": "signer"}, {"slug": "party_2", "kind": "signer"}],
        "fields": [
            {
                "id": found.id,
                "holds": "signature",
                "format": None,
                "filled_by": "party_1" if found.placements[0].rect[0] < 300 else "party_2",
                "label": f"Signature {n}",
                "must_fill": True,
                "depends_on": None,
            }
            for n, found in enumerate(reading.asked)
        ],
        "checkbox_groups": [],
        "extra_fields": [
            {"page": 1, "holds": "full_name", "format": None, "must_fill": True, **extra}
            for extra in [
                {"anchor_text": "NAME:", "filled_by": "party_2", "label": "Wrong name"},
                {"anchor_text": "NAME:", "filled_by": "party_1", "label": "Left name"},
            ]
        ],
        "document": None,
    }
    with pymupdf.open(stream=data, filetype="pdf") as document:
        problems = check(answer, reading, document)
        result = derive(reading, answer, document, problems=problems, repaired=True)
    assert [p for p in problems if "Wrong name" in p]  # the repair round is asked about it
    assert all(f.label != "Wrong name" for f in result.fields)
    assert any("'Wrong name' dropped" in note for note in result.notes)
    left_box = _extra(result, "Left name")
    assert left_box[0] > left.x1 and left_box[2] < 324  # the left party keeps its own column


def test_an_anchor_that_quotes_its_blank_is_placed_after_the_words_before_it() -> None:
    """The AI copied the blank too ("Total: $____"): the label is the words before the blank, and
    a form field already there means no room, so no second field is made over it."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 100), PARAGRAPH, fontsize=11)
    page.insert_text((72, 160), "Total for the first year: $" + "_" * 12, fontsize=11)
    widget = pymupdf.Widget()
    widget.field_name, widget.field_type = "Total", pymupdf.PDF_WIDGET_TYPE_TEXT  # type: ignore[attr-defined]
    widget.rect = pymupdf.Rect(_end("Total for the first year: $"), 148, 240, 163)
    page.add_widget(widget)
    quoted = {"anchor_text": "Total for the first year: $____________", "filled_by": "party_1"}
    result = _with_extras(document.tobytes(), [{**quoted, "label": "Total"}], ["text"])
    assert all(field.label != "Total" for field in result.fields)
    assert any("'Total' dropped" in note for note in result.notes)


def _end(text: str, x: float = 72) -> float:
    return x + pymupdf.get_text_length(text, fontsize=11)


def test_a_form_field_after_the_label_is_that_blank_and_asks_the_ai_nothing() -> None:
    """A total the PDF calculates sits after "Total: $": the AI listing it as a blank is not a
    mistake it can fix with other words, so no repair round; the duplicate is dropped."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 100), PARAGRAPH, fontsize=11)
    page.insert_text((72, 160), "Total for the first year: $", fontsize=11)
    widget = pymupdf.Widget()
    widget.field_name, widget.field_type = "Total", pymupdf.PDF_WIDGET_TYPE_TEXT  # type: ignore[attr-defined]
    widget.rect = pymupdf.Rect(_end("Total for the first year: $") + 2, 148, 300, 163)
    page.add_widget(widget)
    data = document.tobytes()
    reading = read_document(data)
    answer: dict[str, Any] = {
        "roles": [{"slug": "party_1", "kind": "signer"}],
        "fields": [
            {
                "id": found.id,
                "holds": "currency",
                "format": None,
                "filled_by": "party_1",
                "label": "Total",
                "must_fill": True,
                "depends_on": None,
            }
            for found in reading.asked
        ],
        "checkbox_groups": [],
        "extra_fields": [
            {
                "page": 1,
                "anchor_text": "Total for the first year: $",
                "holds": "currency",
                "format": None,
                "filled_by": "party_1",
                "label": "Total again",
                "must_fill": True,
            }
        ],
        "document": None,
    }
    with pymupdf.open(stream=data, filetype="pdf") as opened:
        problems = check(answer, reading, opened)
        result = derive(reading, answer, opened, problems=problems, repaired=False)
    assert not any("Total again" in problem for problem in problems)
    assert all(field.label != "Total again" for field in result.fields)
    assert any("'Total again' dropped: a form field already sits" in n for n in result.notes)


@pytest.mark.parametrize("anchor", ["________", "   ", "_____ Name:"])
def test_an_anchor_that_is_only_its_blank_is_a_problem_not_an_error(anchor: str) -> None:
    """Review #1: an anchor with no words before its blank crashed the check (an empty search
    answers None), so the job retried a paid AI call and failed the version."""
    data = _flat([(72, 100, PARAGRAPH), (72, 300, "Name: ________")])
    extra = {"anchor_text": anchor, "filled_by": "party_1", "label": "Name"}
    reading = read_document(data)
    answer: dict[str, Any] = {
        "roles": [{"slug": "party_1", "kind": "signer"}],
        "fields": [],
        "checkbox_groups": [],
        "extra_fields": [
            {"page": 1, "holds": "full_name", "format": None, "must_fill": True, **extra}
        ],
        "document": None,
    }
    with pymupdf.open(stream=data, filetype="pdf") as document:
        problems = check(answer, reading, document)
        result = derive(reading, answer, document, problems=problems, repaired=True)
    assert any("extra field 'Name'" in problem for problem in problems)
    assert any("'Name' dropped" in note for note in result.notes)


def test_a_signature_line_under_single_spaced_text_never_grows_over_it() -> None:
    """Review #4: the row above overlapped the line's box by about 2 pt, more than the 0.5 pt
    allowed, so it was not an obstacle and the box grew over the sentence above it."""
    data = _flat(
        [
            (72, 290, "In witness whereof the parties have signed this agreement."),
            (72, 303, "Signature: " + LINE),
        ]
    )
    ((before, after),) = _derive(data, ["signature"]).items()
    assert after == before  # no room above: it keeps its size, never covers the sentence


def test_a_second_extra_field_on_the_same_blank_is_a_problem_named_as_such() -> None:
    """Review #7: the check passed it, then derive dropped it blaming a form field that does not
    exist. Listing the same blank twice is the AI's to fix: the repair round says so."""
    data = _flat([(72, 100, PARAGRAPH), (72, 300, "Name:")])
    reading = read_document(data)
    extra = {"page": 1, "anchor_text": "Name:", "holds": "full_name", "format": None}
    answer: dict[str, Any] = {
        "roles": [{"slug": "party_1", "kind": "signer"}],
        "fields": [],
        "checkbox_groups": [],
        "extra_fields": [
            {**extra, "filled_by": "party_1", "label": "First", "must_fill": True},
            {**extra, "filled_by": "party_1", "label": "Second", "must_fill": True},
        ],
        "document": None,
    }
    with pymupdf.open(stream=data, filetype="pdf") as document:
        problems = check(answer, reading, document)
        result = derive(reading, answer, document, problems=problems, repaired=True)
    assert problems == ["extra field 'Second': the same blank as another extra field: list it once"]
    assert [field.label for field in result.fields] == ["First"]
    assert any("'Second' dropped: the same blank as another" in note for note in result.notes)
