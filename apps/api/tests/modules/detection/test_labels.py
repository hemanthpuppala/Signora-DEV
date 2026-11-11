"""Labels read from the page (findings F3, F4, F5): each field named by its own words, never by its
neighbour's; a heading rows above a lone line; a field nothing names is flagged."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pymupdf
import pytest

from signora.modules.detection.derive import derive
from signora.modules.detection.read import read_document

PARAGRAPH = "The parties have executed this Agreement as of the dates written below, in two copies."
U = "_" * 14
Draw = Callable[[pymupdf.Page], object]


def _page(*steps: Draw) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 120), PARAGRAPH, fontsize=11)
    for step in steps:
        step(page)
    data: bytes = document.tobytes()
    return data


def _text(x: float, y: float, text: str, size: float = 11) -> Draw:
    return lambda page: page.insert_text((x, y), text, fontsize=size)


def _field(name: str, rect: tuple[float, float, float, float], tooltip: str | None = None) -> Draw:
    def step(page: pymupdf.Page) -> None:
        widget = pymupdf.Widget()
        widget.field_name, widget.field_type = name, pymupdf.PDF_WIDGET_TYPE_TEXT  # type: ignore[attr-defined]
        widget.rect = pymupdf.Rect(rect)
        if tooltip:
            widget.field_label = tooltip
        page.add_widget(widget)

    return step


def _labels(data: bytes) -> list[str | None]:
    return [found.label for found in read_document(data).asked]


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        pytest.param(
            [_text(72, 300, f"Name: {U}  Date: {U}")], ["Name:", "Date:"], id="two-on-a-row"
        ),
        pytest.param(
            [_text(72, 300, f"made this {U} day of {U}, 20{U}")],
            ["made this", "day of", "20"],
            id="inline-sentence-with-printed-century",
        ),
        pytest.param(
            [_text(72, 300, f"Name: {U}"), _text(320, 300, f"Name: {U}")],
            ["Name:", "Name:"],
            id="two-columns",
        ),
        pytest.param(
            [
                *[
                    _text(x, 290, words)
                    for x, words in ((72, "Year"), (150, "Make"), (260, "Model"))
                ],
                _field("a", (72, 293, 140, 315)),
                _field("b", (150, 293, 250, 315)),
                _field("c", (260, 293, 400, 315)),
            ],
            ["Year", "Make", "Model"],
            id="captions-touching-a-row-of-boxes",
        ),
        pytest.param([_text(72, 300, f"• Name: {U}")], ["Name:"], id="bullet-before"),
        pytest.param(
            [_text(72, 300, "` Section 1:"), _field("s", (160, 290, 300, 304))],
            ["Section 1:"],
            id="stray-mark-before",
        ),
        pytest.param(
            [_text(72, 300, "Name:"), _field("n", (110, 290, 300, 304), "Client full name")],
            ["Client full name"],
            id="tooltip-wins",
        ),
        pytest.param(
            [
                _text(72, 300, "Notice Address"),
                _text(72, 311, "Use email", 8),
                _field("n", (200, 290, 450, 320)),
            ],
            ["Notice Address · Use email"],
            id="label-cell-of-two-lines",
        ),
    ],
)
def test_each_field_is_named_by_its_own_words(steps: list[Draw], expected: list[str]) -> None:
    assert _labels(_page(*steps)) == expected


def test_a_heading_rows_above_a_lone_line_names_it() -> None:
    """F3: "Company Representative's Signature" 45 pt above its line, "Print Name" 35 pt above."""
    data = _page(
        _text(72, 400, "Company Representative's Signature"),
        _text(72, 445, U * 2),
        _text(72, 500, "Print Name"),
        _text(72, 535, U * 2),
    )
    assert _labels(data) == ["Company Representative's Signature", "Print Name"]


def test_a_far_heading_never_passes_another_field_nor_beats_a_left_label() -> None:
    data = _page(_text(72, 400, "Witness"), _text(72, 420, f"Name: {U}"), _text(300, 445, U))
    assert _labels(data) == ["Name:", None]


def test_a_caption_below_a_line_still_names_it() -> None:
    assert _labels(_page(_text(72, 600, U * 2), _text(72, 612, "Seller's signature", 8))) == [
        "Seller's signature"
    ]


def _answered(data: bytes, label: str) -> Any:
    reading = read_document(data)
    answer: dict[str, Any] = {
        "roles": [{"slug": "client", "kind": "signer"}],
        "fields": [
            {
                "id": found.id,
                "holds": "text",
                "format": None,
                "filled_by": "client",
                "label": label,
                "must_fill": True,
                "depends_on": None,
            }
            for found in reading.asked
        ],
        "checkbox_groups": [],
        "extra_fields": [],
        "document": None,
    }
    with pymupdf.open(stream=data, filetype="pdf") as document:
        return derive(reading, answer, document, problems=[], repaired=False)


def test_a_field_nothing_names_is_flagged_for_a_look() -> None:
    """F4: no words on the page name it and the AI's label is refused (it held a link)."""
    data = _page(_text(72, 300, f"{U} (initials)"))
    (field,) = _answered(data, "see https://example.com").fields
    assert field.needs_review is not None and "nothing on the page names it" in field.needs_review


def test_a_field_the_ai_names_is_not_flagged_for_its_missing_page_label() -> None:
    data = _page(_text(72, 300, f"{U} (initials)"))
    (field,) = _answered(data, "Initials").fields
    assert field.needs_review is None


def test_a_caption_overlapping_its_fields_top_edge_names_it() -> None:
    """A government form's cell: the caption's middle is above the field, its foot 2.6 pt inside."""
    data = _page(
        _text(50, 180.5, "Year", 8),
        _text(140, 180.5, "Make/Manufacturer", 8),
        _field("year", (46, 180.1, 134, 198.6)),
        _field("make", (136, 180.1, 273, 198.6)),
    )
    assert _labels(data) == ["Year", "Make/Manufacturer"]


def test_a_caption_printed_inside_the_top_of_its_cell_names_it() -> None:
    data = _page(_text(76, 296, "Color", 7), _field("color", (72, 288, 200, 316)))
    (found,) = read_document(data).asked
    assert (found.caption, found.label) == ("Color", "Color")


def test_a_lone_line_under_another_field_takes_no_label_from_past_it() -> None:
    """A wrapped blank ("____, of / ______, City of"): the line above is past another field, so
    no label rather than a misleading one; the AI reads it in its sentence."""
    data = _page(_text(72, 300, f"{U}, 20{U}"), _text(72, 314, f"{U}, City of"))
    assert _labels(data)[2] is None


def test_two_blanks_drawn_under_spaces_on_one_line_each_take_their_label() -> None:
    """Review #3: no word sits on a line drawn under spaces, so "Name: … Date: …" stayed one
    piece of text spanning the first blank, and both blanks lost their labels."""
    line = "Name:" + " " * 30 + "Date:" + " " * 25

    def width(text: str) -> float:
        return float(pymupdf.get_text_length(text, fontsize=11))

    def underlines(page: pymupdf.Page) -> None:
        page.draw_line((72 + width("Name: "), 302), (72 + width("Name:" + " " * 29), 302))
        page.draw_line((72 + width("Name:" + " " * 30 + "Date: "), 302), (72 + width(line), 302))

    assert _labels(_page(_text(72, 300, line), underlines)) == ["Name:", "Date:"]
