"""Blank lines drawn as graphics (findings F1): a thin line with nothing written on it is a blank;
underlined words, lines under found blanks, separators, table borders and unlabelled header and
footer rules are not."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pymupdf
import pytest

from signora.modules.detection.derive import derive
from signora.modules.detection.read import read_document
from signora.modules.detection.reading import FoundField

PARAGRAPH = "The parties have executed this Agreement as of the dates written below, in two copies."
Draw = Callable[[pymupdf.Page], object]


def _page(*steps: Draw, rotation: int = 0) -> bytes:
    """A flat page with a paragraph (it sets the text's width) and the given drawing steps."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 200), PARAGRAPH, fontsize=11)
    for step in steps:
        step(page)
    page.set_rotation(rotation)
    data: bytes = document.tobytes()
    return data


def _text(x: float, y: float, text: str) -> Draw:
    return lambda page: page.insert_text((x, y), text, fontsize=11)


def _line(x0: float, x1: float, y: float) -> Draw:
    return lambda page: page.draw_line((x0, y), (x1, y), width=0.75)


def _bar(x0: float, x1: float, y: float) -> Draw:
    """A line drawn as a thin filled rectangle, as word processors draw underlines."""
    return lambda page: page.draw_rect(pymupdf.Rect(x0, y, x1, y + 0.8), color=None, fill=(0, 0, 0))


def _drawn(data: bytes) -> list[FoundField]:
    return [found for found in read_document(data).asked if found.drawn]


def _end(text: str, x: float = 72) -> float:
    return x + pymupdf.get_text_length(text, fontsize=11)


def test_underlined_spaces_after_a_label_are_a_blank_labelled_by_it() -> None:
    (blank,) = _drawn(_page(_text(72, 300, "Name:"), _line(_end("Name:") + 4, 260, 302)))
    assert blank.kind == "blank" and blank.label == "Name:"


def test_a_line_drawn_as_a_thin_bar_is_a_blank_too() -> None:
    assert len(_drawn(_page(_text(72, 300, "Date:"), _bar(_end("Date:") + 4, 200, 302)))) == 1


def test_no_break_spaces_on_the_line_leave_it_empty() -> None:
    spaces = "\u00a0" * 20
    data = _page(_text(72, 300, "Name:" + spaces), _line(_end("Name:") + 2, 220, 302))
    assert len(_drawn(data)) == 1


def test_one_underline_under_a_label_and_its_spaces_gives_the_stretch_after_the_label() -> None:
    data = _page(_text(72, 300, "Name:"), _line(72, 260, 302))
    (blank,) = _drawn(data)
    assert blank.placements[0].rect[0] >= _end("Name:")  # after the label, not under it


def test_an_underlined_word_is_not_a_blank() -> None:
    assert _drawn(_page(_text(72, 300, "Disclosing"), _line(72, _end("Disclosing"), 302))) == []


def test_a_line_under_typed_underscores_is_not_found_twice() -> None:
    data = _page(
        _text(72, 300, "Name: " + "_" * 30), _line(_end("Name: "), _end("Name: " + "_" * 30), 302)
    )
    assert _drawn(data) == [] and len(read_document(data).asked) == 1


def test_a_separator_across_the_text_is_not_a_blank_even_drawn_in_pieces() -> None:
    """A table's row rule is often drawn once per column: joined, it is one separator."""
    right = _end(PARAGRAPH)
    whole = _page(_line(72, right, 260))
    pieces = _page(_line(72, 225, 260), _line(225.5, right, 260))
    assert _drawn(whole) == [] and _drawn(pieces) == []


def test_a_ruled_tables_borders_are_not_blanks() -> None:
    def table(page: pymupdf.Page) -> None:
        for y in (240, 260, 280):
            page.draw_line((72, y), (300, y), width=0.75)
        for x in (72, 186, 300):
            page.draw_line((x, 240), (x, 280), width=0.75)

    assert _drawn(_page(table)) == []


def test_an_unlabelled_footer_rule_is_not_a_blank_but_footer_initials_are() -> None:
    footer = _page(_line(72, 300, 760))
    initials = _page(_text(72, 760, "Initials:"), _line(_end("Initials:") + 4, 160, 762))
    assert _drawn(footer) == []
    (blank,) = _drawn(initials)
    assert blank.label == "Initials:"


def test_a_line_under_a_form_field_is_not_a_blank() -> None:
    def field(page: pymupdf.Page) -> None:
        widget = pymupdf.Widget()
        widget.field_name, widget.field_type = "Name", pymupdf.PDF_WIDGET_TYPE_TEXT  # type: ignore[attr-defined]
        widget.rect = pymupdf.Rect(110, 288, 260, 302)
        page.add_widget(widget)

    data = _page(_text(72, 300, "Name:"), _line(110, 260, 302), field)
    reading = read_document(data)
    assert [found.kind for found in reading.asked] == ["text"]


def test_on_a_turned_page_a_drawn_blank_is_placed_as_the_page_is_shown() -> None:
    data = _page(_text(72, 300, "Name:"), _line(_end("Name:") + 4, 260, 302), rotation=90)
    (blank,) = _drawn(data)
    shown = pymupdf.open(stream=data, filetype="pdf")[0].rect
    x0, y0, x1, y1 = blank.placements[0].rect
    assert 0 <= x0 < x1 <= shown.width and 0 <= y0 < y1 <= shown.height


@pytest.mark.parametrize(("filled_by", "kept"), [("none", False), ("client", True)])
def test_a_drawn_line_the_ai_says_nobody_fills_is_not_kept(filled_by: str, kept: bool) -> None:
    data = _page(_text(72, 300, "Name:"), _line(_end("Name:") + 4, 260, 302))
    reading = read_document(data)
    (blank,) = reading.asked
    answer: dict[str, Any] = {
        "roles": [{"slug": "client", "kind": "signer"}],
        "fields": [
            {
                "id": blank.id,
                "holds": "full_name",
                "format": None,
                "filled_by": filled_by,
                "label": "Name",
                "must_fill": True,
                "depends_on": None,
            }
        ],
        "checkbox_groups": [],
        "extra_fields": [],
        "document": None,
    }
    with pymupdf.open(stream=data, filetype="pdf") as document:
        result = derive(reading, answer, document, problems=[], repaired=False)
    assert bool(result.fields) is kept
    assert any("drawn line nobody fills" in note for note in result.notes) is not kept
