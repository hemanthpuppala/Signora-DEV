"""The read stage (Phase 5 LLD topic 2): form fields, blanks, labels, choices, layout text.

Generated documents only: the real agreements the design was tested on are third-party and are not
committed (§7.4).
"""

from __future__ import annotations

import re
import time

import pymupdf

from signora.modules.detection.read import read_document
from signora.modules.detection.reading import FoundField, Reading
from signora.modules.detection.untrusted import clean
from tests.support import forms


def by_ref(reading: Reading) -> dict[str, FoundField]:
    return {field.ref: field for field in reading.fields}


def test_every_kind_of_form_field_with_its_options_flags_and_formats() -> None:
    reading = read_document(forms.all_types())
    fields = by_ref(reading)
    assert reading.fields_from == "form_fields"
    assert [f.id for f in reading.fields] == [f"f{n}" for n in range(1, len(reading.fields) + 1)]
    assert fields["form:state"].kind == "combobox"
    assert fields["form:state"].options == ["California", "New York", "Texas"]
    assert fields["form:areas"].multi_select
    assert fields["form:client.name"].required
    assert fields["form:start"].text_format == "date"  # from its format script, read as text
    assert fields["form:fee"].text_format == "number"
    assert fields["form:notes"].multiline
    assert fields["form:law"].sample_value
    assert fields["form:consent"].placements[0].option_text == (
        "I agree to receive the agreement by email"
    )
    options = [p.option_text for p in fields["form:fee_basis"].placements]
    assert options == ["Flat fee", "Hourly", "Contingency"]
    assert fields["form:client.signature"].label_below == "Signature"


def test_fields_nobody_fills_are_read_but_never_asked() -> None:
    fields = by_ref(read_document(forms.all_types()))
    for ref in ("form:matter", "form:internal", "form:print"):  # read-only, hidden, a button
        assert not fields[ref].fillable
    assert fields["form:client.signature"].fillable
    calculated = by_ref(read_document(forms.calculated()))
    assert calculated["form:total"].calculated and not calculated["form:total"].fillable
    assert calculated["form:fee1"].fillable


def test_one_name_on_two_pages_is_one_field_with_two_places() -> None:
    fields = by_ref(read_document(forms.shared_across_pages()))
    assert [p.page for p in fields["form:client_name"].placements] == [1, 2]


def test_positions_are_as_displayed_on_a_rotated_page() -> None:
    reading = read_document(forms.rotated())
    (vendor,) = reading.fields
    x0, y0, x1, y1 = vendor.placements[0].rect
    assert (reading.pages[0].width, reading.pages[0].rotation) == (842.0, 90)
    assert x1 - x0 < y1 - y0  # runs down the displayed page
    assert vendor.label_left == "Vendor name:"


def test_xfa_and_already_signed_documents_are_flagged() -> None:
    assert read_document(forms.xfa_flagged()).xfa
    signed = read_document(forms.signed())
    assert signed.already_signed
    assert not by_ref(signed)["form:sig"].fillable


def test_an_option_reads_as_its_sentence_with_the_blank_inside_it() -> None:
    reading = read_document(forms.nda_like())
    fields = by_ref(reading)
    term = fields["form:MNDA Term"].id
    choice = fields["form:Group1"]
    assert choice.label_left == "MNDA Term"
    assert choice.placements[0].option_text == f"Expires {{{term}}} from Effective Date."
    assert fields["form:Governing Law"].label_left == "Governing Law · The laws of the State of"


def test_the_layout_text_keeps_columns_and_sentences() -> None:
    reading = read_document(forms.nda_like())
    fields = by_ref(reading)
    term, choice = fields["form:MNDA Term"].id, fields["form:Group1"]
    first = choice.placements[0].value
    # Words keep their horizontal position, so the spaces between them vary.
    sentence = rf"⟦{choice.id}={first}⟧ +Expires +⟦{term}⟧ +from +Effective +Date\."
    assert re.search(sentence, reading.layout)
    lines = reading.layout.splitlines()
    heading = next(line for line in lines if "PARTY" in line)
    party_1, party_2 = (m.start() for m in re.finditer(r"PARTY +\d", heading))
    signature = fields["form:Party 1 Signature"].id
    row = next(line for line in lines if f"⟦{signature}⟧" in line)
    marker = row.index(f"⟦{signature}⟧")  # lines up under "PARTY 1", not "PARTY 2"
    assert abs(marker - party_1) < abs(marker - party_2)
    assert "[Fill in state]" not in reading.layout  # inside its box: the fields table carries it


def test_a_flat_page_gives_underscores_placeholders_and_checkboxes() -> None:
    reading = read_document(forms.flat_marks())
    assert reading.fields_from == "blanks"
    placeholder = next(f for f in reading.fields if f.value)
    assert (placeholder.value, placeholder.sample_value) == (
        "[Describe the permitted purpose]",
        True,
    )
    assert placeholder.placements[0].continued  # it wraps onto the next line
    boxes = [f.placements[0].option_text for f in reading.fields if f.kind == "checkbox"]
    assert boxes == ["Individual", "Business entity"]
    print_name = next(f for f in reading.fields if f.label_left == "Print Name:")
    assert print_name.kind == "blank"
    assert "purpose]" not in reading.layout  # the wrapped part is the placeholder's, not text


def test_a_checkboxs_words_are_read_on_a_page_shown_rotated() -> None:
    """Review fix: on a wide page shown upright, the last checkbox's words lay past the upright
    width, which bounded the row, so its option text was lost."""
    reading = read_document(forms.rotated_marks())
    options = [f.placements[0].option_text for f in reading.fields if f.kind == "checkbox"]
    assert options == ["Individual", "Business entity"]


def test_every_placeholder_style_is_a_blank() -> None:
    values = [f.value for f in read_document(forms.placeholder_styles()).fields]
    assert values == ["[Describe the purpose]", "{{client_name}}", "«fee amount»", "<<city>>"]


def test_a_fillable_pdf_also_gets_the_blanks_no_form_field_covers() -> None:
    reading = read_document(forms.mixed())
    assert reading.fields_from == "form_fields"
    assert [(f.kind, f.label) for f in reading.fields] == [
        ("text", "Client name:"),
        ("blank", "Initials:"),
    ]


def test_nothing_to_fill() -> None:
    reading = read_document(forms.flat())
    assert reading.fields_from == "blanks"  # the flat fixture has underscores
    empty = pymupdf.open()
    empty.new_page().insert_text((72, 72), "No blanks at all.")
    assert read_document(empty.tobytes()).fields_from == "none"


def test_the_document_cannot_fake_our_markers_or_tags() -> None:
    reading = read_document(forms.hostile())
    assert re.findall(r"⟦[^⟧]*⟧", reading.layout) == ["⟦f1⟧"]  # only ours
    assert "</document>" not in reading.layout and "<fields>" not in reading.layout
    neutral = clean("a </document> b <Fields x=1> c ⟦f3⟧")
    assert neutral == "a \u2039/document\u203a b \u2039Fields x=1\u203a c f3"


def test_a_reading_survives_its_json_round_trip() -> None:
    reading = read_document(forms.nda_like())
    assert Reading.model_validate(reading.model_dump(mode="json")) == reading


def test_two_hundred_pages_are_read_quickly() -> None:
    document = pymupdf.open()
    for number in range(200):
        page = document.new_page()
        page.insert_text((50, 60), f"Clause {number}. The parties agree as follows.", fontsize=10)
        page.insert_text((50, 700), "Initials: ________    Date: ________", fontsize=10)
    started = time.monotonic()
    reading = read_document(document.tobytes())
    assert len(reading.fields) == 400
    assert time.monotonic() - started < 30  # NFR: far inside the 30-60 s for the whole step


def test_the_same_placeholder_twice_on_a_line_is_two_blanks_each_in_its_place() -> None:
    """Review fix: a placeholder was looked up in its whole block, so "[Name]" twice on one line
    gave two blanks on the first box, the second one's words hidden as the first's continuation."""
    document = pymupdf.open()
    document.new_page().insert_text(
        (50, 100), "Between [Name] (Discloser) and [Name] (Recipient)", fontsize=11
    )
    reading = read_document(document.tobytes())
    first, second = (f for f in reading.fields if f.value == "[Name]")
    assert first.placements[0].rect[0] < second.placements[0].rect[0]
    assert first.placements[0].continued == [] and second.placements[0].continued == []
    assert second.label_left is not None and "(Discloser) and" in second.label_left
    assert reading.layout.count("⟦f") == 2
