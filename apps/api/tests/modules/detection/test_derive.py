"""Checking the answer and building the version's fields (Phase 5 LLD topic 4)."""

from __future__ import annotations

from typing import Any

import pymupdf

from signora.modules.detection.derive import check, derive
from signora.modules.detection.read import read_document
from signora.modules.detection.reading import Reading
from tests.support import forms


def _open(data: bytes) -> tuple[Reading, pymupdf.Document]:
    return read_document(data), pymupdf.open(stream=data, filetype="pdf")


def _ids(reading: Reading) -> dict[str, str]:
    """PDF field name (or blank label) -> id."""
    return {(f.pdf_field or f.label or f.ref): f.id for f in reading.asked}


def _field(id_: str, holds: str, filled_by: str, label: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": id_,
        "holds": holds,
        "format": extra.pop("format", None),
        "filled_by": filled_by,
        "label": label,
        "must_fill": extra.pop("must_fill", True),
        "depends_on": extra.pop("depends_on", None),
    }


def _answer(fields: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "roles": extra.pop(
            "roles", [{"slug": "party_1", "kind": "signer"}, {"slug": "party_2", "kind": "signer"}]
        ),
        "fields": fields,
        "checkbox_groups": extra.pop("checkbox_groups", []),
        "extra_fields": extra.pop("extra_fields", []),
        "document": extra.pop("document", None),
    }


def _nda_answer(reading: Reading, **changes: Any) -> dict[str, Any]:
    ids = _ids(reading)
    fields = [
        _field(ids["Governing Law"], "state", "sender", "Governing law: state"),
        _field(ids["Group1"], "choice", "sender", "MNDA term"),
        _field(
            ids["MNDA Term"],
            "number",
            "sender",
            "MNDA term in years",
            depends_on=changes.pop(
                "term_depends",
                {"id": ids["Group1"], "option": reading.fields[0].options[0] if False else "True"},
            ),
        ),
        _field(ids["Party 1 Signature"], "signature", "party_1", "Party 1 signature"),
        _field(ids["Party 2 Signature"], "signature", "party_2", "Party 2 signature"),
        _field(ids["Party 1 Print Name"], "full_name", "party_1", "Party 1 print name"),
        _field(ids["Party 2 Print Name"], "full_name", "party_2", "Party 2 print name"),
    ]
    return _answer(fields, **changes)


def test_a_good_answer_passes_and_becomes_one_field_per_key() -> None:
    reading, document = _open(forms.nda_like())
    answer = _nda_answer(reading)
    assert check(answer, reading, document) == []
    result = derive(reading, answer, document, problems=[], repaired=False)
    keys = [f.key for f in result.fields]
    assert keys == [
        "agreement.governing_law_state",
        "agreement.mnda_term_in_years",  # its box sits 2 pt above the radio group's first option
        "agreement.mnda_term",
        "party_1.signature",
        "party_2.signature",
        "party_1.full_name",
        "party_2.full_name",
    ]
    choice = next(f for f in result.fields if f.key == "agreement.mnda_term")
    assert [p.option_value for p in choice.placements] == ["True", "False"]  # the PDF's on-states
    assert [p.pdf_field for p in choice.placements] == ["Group1", "Group1"]
    assert [(r.slug, r.kind, r.label, r.position) for r in result.roles] == [
        ("party_1", "signer", "Party 1", 1),
        ("party_2", "signer", "Party 2", 2),
    ]
    assert not result.flags.no_fields and result.notes == []


def test_the_layout_dependency_wins_over_the_ais() -> None:
    reading, document = _open(forms.nda_like())
    ids = _ids(reading)
    answer = _nda_answer(reading, term_depends=None)  # the AI missed it
    result = derive(reading, answer, document, problems=[], repaired=False)
    term = next(f for f in result.fields if f.key == "agreement.mnda_term_in_years")
    assert term.depends_on is not None
    assert (term.depends_on.key, term.depends_on.option, term.depends_on.source) == (
        "agreement.mnda_term",
        "True",
        "layout",
    )
    assert (
        any(note.startswith(f"{ids['MNDA Term']}: the AI said") for note in result.notes) is False
    )


def test_dependencies_that_loop_are_broken_and_flagged() -> None:
    """Review fix: two fields each shown only when the other is filled vanished from the panel's
    tree (neither was a root). The loop is broken at the AI's link, and that field needs a look."""
    reading, document = _open(forms.all_types())
    on_fee = {"id": "f11", "option": "True"}
    on_consent = {"id": "f10", "option": "checked"}
    answer = _answer(
        [
            _field("f10", "checkbox", "sender", "Consent", depends_on=on_fee),
            _field("f11", "choice", "sender", "Fee basis", depends_on=on_consent),
        ]
    )
    result = derive(reading, answer, document, problems=[], repaired=False)
    by_label = {f.label: f for f in result.fields}
    consent, fee = by_label["Consent"], by_label["Fee basis"]
    linked = [f for f in (consent, fee) if f.depends_on is not None]
    assert len(linked) == 1  # one link kept: the two fields form a chain, not a loop
    cut = fee if linked == [consent] else consent
    assert cut.needs_review is not None and "loop" in cut.needs_review
    assert linked[0].depends_on is not None and linked[0].depends_on.key == cut.key


def test_a_condition_on_a_field_someone_else_fills_is_dropped_and_flagged() -> None:
    """Whoever fills a field must be the one who answers what it depends on: the sender's fee
    under a party's tick could never be asked of the sender in time. Review refuses such a
    condition, so a proposal never carries one."""
    reading, document = _open(forms.all_types())
    answer = _answer(
        [
            _field("f10", "checkbox", "party_1", "Consent"),
            _field(
                "f11",
                "choice",
                "sender",
                "Fee basis",
                depends_on={"id": "f10", "option": "checked"},
            ),
            _field(
                "f12", "text", "party_1", "Notes", depends_on={"id": "f10", "option": "checked"}
            ),
        ]
    )
    result = derive(reading, answer, document, problems=[], repaired=False)
    by_label = {f.label: f for f in result.fields}
    fee, notes = by_label["Fee basis"], by_label["Notes"]
    assert fee.depends_on is None
    assert fee.needs_review is not None and "someone else fills" in fee.needs_review
    assert notes.depends_on is not None and notes.needs_review is None  # the same party: kept


def test_every_check_finds_its_problem() -> None:
    reading, document = _open(forms.nda_like())
    ids = _ids(reading)
    answer = _nda_answer(
        reading,
        roles=[
            {"slug": "party_1", "kind": "countersigner"},
            {"slug": "witness", "kind": "countersigner"},
        ],
        document={"name": "x" * 130, "description": "See https://evil.example now"},
        extra_fields=[
            {
                "page": 1,
                "anchor_text": "Nowhere in this document",
                "holds": "initials",
                "format": None,
                "filled_by": "party_1",
                "label": "Initials",
                "must_fill": True,
            }
        ],
    )
    answer["fields"][0]["holds"] = (
        "signature"  # a text box holding a signature is fine; a radio isn't
    )
    answer["fields"][1]["holds"] = "text"  # the radio group
    answer["fields"][3]["filled_by"] = "sender"  # a signature by the sender
    answer["fields"][4]["filled_by"] = "party_9"  # not a listed role
    answer["fields"].pop()  # Party 2 print name unanswered
    answer["fields"].append(dict(answer["fields"][0]))  # Governing Law answered twice
    answer["fields"][2]["depends_on"] = {"id": ids["Group1"], "option": "Maybe"}
    answer["fields"][5]["label"] = "<b>Party 1</b> print name"
    problems = check(answer, reading, document)
    expected = [
        "no role is a signer",
        f"{ids['Party 2 Print Name']}: answered 0 times",
        f"{ids['Governing Law']}: answered 2 times",
        "roles that fill nothing: ['witness']",
        f"{ids['Party 1 Signature']}: a signature must be given by a party",
        f"{ids['Party 2 Signature']}: filled_by 'party_9' is not a listed role",
        f"{ids['Party 1 Print Name']}: the label has a link or markup",
        f"{ids['Group1']}: a radio cannot hold text",
        "which is not an option",
        "extra field 'Initials': its words are not on page 1",
        "the name has 130 characters",
        "the name or description has a link or markup",
    ]
    for wanted in expected:
        assert any(wanted in problem for problem in problems), wanted


def test_problems_that_remain_are_resolved_and_flagged_never_failed() -> None:
    reading, document = _open(forms.nda_like())
    ids = _ids(reading)
    answer = _nda_answer(reading, document={"name": "See www.evil.example", "description": "Fine."})
    answer["fields"][1]["holds"] = "text"  # a radio group cannot hold text
    answer["fields"][4]["filled_by"] = "party_9"
    answer["fields"].pop()  # Party 2 print name unanswered
    answer["fields"][5]["label"] = "Click [here](https://x.example)"
    problems = check(answer, reading, document)
    result = derive(reading, answer, document, problems=problems, repaired=True)
    by_id = {i: f for f in result.fields for i in f.ids}
    assert by_id[ids["Group1"]].holds == "choice"
    assert by_id[ids["Party 2 Signature"]].filled_by == "none"
    unassigned = by_id[ids["Party 2 Print Name"]]
    assert (unassigned.filled_by, unassigned.needs_review) == ("none", "not assigned to anyone")
    assert by_id[ids["Party 1 Print Name"]].label == "Print Name"  # the PDF's label instead
    assert by_id[ids["Group1"]].needs_review == "a radio cannot hold text"
    assert result.document is not None and result.document.name is None
    assert result.flags.name_dropped and result.flags.repaired


def test_values_given_once_and_checkbox_groups_are_one_key() -> None:
    reading, document = _open(forms.flat_marks())
    boxes = [f.id for f in reading.asked if f.kind == "checkbox"]
    print_name = next(f.id for f in reading.asked if f.label == "Print Name:")
    purpose = next(f.id for f in reading.asked if f.value)
    answer = _answer(
        [
            _field(boxes[0], "checkbox", "client", "Client is an individual"),
            _field(boxes[1], "checkbox", "client", "Client is a business"),
            _field(
                print_name,
                "party_name",
                "client",
                "Client name",
                depends_on={"id": boxes[0], "option": "checked"},
            ),
            _field(purpose, "text", "sender", "Purpose"),
        ],
        roles=[{"slug": "client", "kind": "signer"}],
        checkbox_groups=[{"ids": boxes, "label": "Client type"}],
    )
    assert check(answer, reading, document) == []
    result = derive(reading, answer, document, problems=[], repaired=False)
    choice = next(f for f in result.fields if f.key == "client.type")
    assert (choice.holds, choice.ids) == ("choice", boxes)
    assert [p.option_value for p in choice.placements] == ["Individual", "Business entity"]
    name = next(f for f in result.fields if f.key == "client.party_name")
    assert name.depends_on is not None
    assert (name.depends_on.key, name.depends_on.option) == ("client.type", "Individual")


def test_initials_on_every_page_are_one_value_in_every_place() -> None:
    document = pymupdf.open()
    for _ in range(3):
        document.new_page().insert_text((50, 700), "Initials: ________", fontsize=10)
    data = document.tobytes()
    reading, opened = _open(data)
    answer = _answer(
        [
            _field(f.id, "initials", "client", f"Client initials, page {f.placements[0].page}")
            for f in reading.asked
        ],
        roles=[{"slug": "client", "kind": "signer"}],
    )
    result = derive(reading, answer, opened, problems=[], repaired=False)
    (initials,) = result.fields
    assert (initials.key, len(initials.placements), initials.ids) == (
        "client.initials",
        3,
        ["f1", "f2", "f3"],
    )


def test_an_extra_field_is_placed_from_its_words_and_one_not_found_is_dropped() -> None:
    reading, document = _open(forms.nda_like())
    answer = _nda_answer(
        reading,
        extra_fields=[
            {
                "page": 1,
                "anchor_text": "Continues until terminated.",
                "holds": "initials",
                "format": None,
                "filled_by": "party_1",
                "label": "Initials",
                "must_fill": True,
            },
            {
                "page": 1,
                "anchor_text": "Not in the document",
                "holds": "text",
                "format": None,
                "filled_by": "sender",
                "label": "Ghost",
                "must_fill": False,
            },
        ],
    )
    result = derive(reading, answer, document, problems=[], repaired=False)
    extra = next(f for f in result.fields if f.key == "party_1.initials")
    assert extra.placements[0].kind == "blank" and extra.ids == []
    assert extra.needs_review == "placed after the words printed before it: check its position"
    (words,) = document[0].search_for("Continues until terminated.")
    assert extra.placements[0].rect[0] > words.x1  # after its words, never on them
    assert any("'Ghost' dropped" in note for note in result.notes)


def test_an_extra_signature_is_a_partys_never_the_senders() -> None:
    """Review fix: extra fields skipped the rule found fields follow, so a signature the AI gave
    to the sender was stored as "filled in before sending"."""
    reading, document = _open(forms.nda_like())
    answer = _nda_answer(
        reading,
        extra_fields=[
            {
                "page": 1,
                "anchor_text": "Continues until terminated.",
                "holds": "signature",
                "format": None,
                "filled_by": "sender",
                "label": "Witness signature",
                "must_fill": True,
            }
        ],
    )
    result = derive(reading, answer, document, problems=[], repaired=False)
    extra = next(f for f in result.fields if f.label == "Witness signature")
    assert (extra.filled_by, extra.role) == ("none", None)  # nobody yet: a person assigns it


def test_flags_keys_and_sensitive_values() -> None:
    reading, document = _open(forms.hostile())
    (blank,) = reading.asked
    answer = _answer(
        [
            _field(
                blank.id,
                "tax_id",
                "recipient",
                "Recipient taxpayer identification number used for payments",
            )
        ],
        roles=[{"slug": "recipient", "kind": "signer"}],
    )
    result = derive(reading, answer, document, problems=[], repaired=False)
    (field,) = result.fields
    assert result.flags.addressed_to_ai
    assert (field.key, field.sensitive) == ("recipient.tax_id", True)
    long_label = _answer(
        [
            _field(
                blank.id,
                "text",
                "recipient",
                "Recipient taxpayer identification number used for payments",
            )
        ],
        roles=[{"slug": "recipient", "kind": "signer"}],
    )
    (named,) = derive(reading, long_label, document, problems=[], repaired=False).fields
    # The role's own word dropped, then cut at a word boundary within 40 characters.
    assert named.key == "recipient.taxpayer_identification_number_used_for"
    empty = pymupdf.open()
    empty.new_page().insert_text((72, 72), "Nothing to fill.")
    data = empty.tobytes()
    nothing, opened = _open(data)
    flat = derive(nothing, _answer([], roles=[]), opened, problems=[], repaired=False)
    assert flat.flags.no_fields and flat.fields == []


def _glyphs(page: pymupdf.Page, at: tuple[float, float], text: str) -> None:
    writer = pymupdf.TextWriter(page.rect)
    writer.append(at, text, font=pymupdf.Font("cjk"), fontsize=11)  # has the ballot box glyph
    writer.write_text(page)


def test_two_checkbox_groups_with_one_label_are_two_choices() -> None:
    """Review fix: groups were told apart by their label, so two "Yes or no" questions became one
    choice with four options (and signing could tick one box across both)."""
    document = pymupdf.open()
    page = document.new_page()
    _glyphs(page, (50, 100), "Q1  ☐ Yes   ☐ No")
    _glyphs(page, (50, 130), "Q2  ☐ Yes   ☐ No")
    reading, opened = _open(document.tobytes())
    first, second = [f.id for f in reading.asked][:2], [f.id for f in reading.asked][2:]
    answer = _answer(
        [
            _field(i, "checkbox", "client", "Yes" if n % 2 == 0 else "No")
            for n, i in enumerate(first + second)
        ],
        roles=[{"slug": "client", "kind": "signer"}],
        checkbox_groups=[
            {"ids": first, "label": "Yes or no"},
            {"ids": second, "label": "Yes or no"},
        ],
    )
    result = derive(reading, answer, opened, problems=[], repaired=False)
    assert [(f.key, f.label, f.ids) for f in result.fields] == [
        ("client.yes_or_no", "Yes or no", first),
        ("client.yes_or_no_2", "Yes or no", second),
    ]


def test_a_dependency_on_a_grouped_checkbox_without_words_names_its_option_as_stored() -> None:
    """Review fix: a grouped checkbox with no words beside it stood for its label as an option,
    while a field depending on it still said "checked", which no option matched."""
    document = pymupdf.open()
    page = document.new_page()
    _glyphs(page, (50, 100), "Entity: ☐")  # no words after the glyph
    _glyphs(page, (300, 100), "☐ Person")
    page.insert_text((50, 130), "Tax id: __________", fontsize=11)
    reading, opened = _open(document.tobytes())
    business, person, tax_id = (f.id for f in reading.asked)
    answer = _answer(
        [
            _field(business, "checkbox", "client", "Business"),
            _field(person, "checkbox", "vendor", "Person"),  # the vendor's only box
            _field(
                tax_id,
                "tax_id",
                "client",
                "Tax id",
                depends_on={"id": business, "option": "checked"},
            ),
        ],
        roles=[{"slug": "client", "kind": "signer"}, {"slug": "vendor", "kind": "signer"}],
        checkbox_groups=[{"ids": [business, person], "label": "Entity type"}],
    )
    result = derive(reading, answer, opened, problems=[], repaired=False)
    choice = next(f for f in result.fields if f.key == "client.entity_type")
    assert [p.option_value for p in choice.placements] == ["Business", "Person"]
    tax = next(f for f in result.fields if f.key == "client.tax_id")
    assert tax.depends_on is not None and tax.depends_on.option == "Business"
    # Review fix: roles were counted before the merge, so the vendor (whose only checkbox joined
    # the client's choice) was stored as a signer with no fields.
    assert [r.slug for r in result.roles] == ["client"]
    assert "roles that fill nothing dropped: ['vendor']" in result.notes


def test_a_signature_box_holding_the_wrong_value_falls_back_to_a_signature() -> None:
    """Review fix: a signature widget had no default, so one the AI mislabelled was stored as
    text in a signature box."""
    document = pymupdf.open()
    widget = pymupdf.Widget()
    widget.field_name, widget.field_type = "Sig", pymupdf.PDF_WIDGET_TYPE_SIGNATURE  # type: ignore[attr-defined]
    widget.rect = pymupdf.Rect(50, 50, 200, 90)
    document.new_page().add_widget(widget)
    reading, opened = _open(document.tobytes())
    (signature,) = reading.asked
    answer = _answer(
        [_field(signature.id, "party_name", "client", "Client signs")],
        roles=[{"slug": "client", "kind": "signer"}],
    )
    problems = check(answer, reading, opened)
    (field,) = derive(reading, answer, opened, problems=problems, repaired=True).fields
    assert (field.key, field.holds, field.placements[0].kind) == (
        "client.signature",
        "signature",
        "signature",
    )
    assert field.needs_review == "a signature cannot hold party_name"


def test_one_value_whose_places_disagree_on_their_condition_applies_always_and_is_flagged() -> None:
    """Review fix: a shared value kept only its first place's condition, so initials inside an
    optional addendum lost theirs silently. A field applies as a whole: it applies always, and the
    person is told to check."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 100), "Initials: ______", fontsize=11)
    _glyphs(page, (50, 130), "Addendum ☐ applies")
    page.insert_text((50, 160), "Initials: ______", fontsize=11)
    reading, opened = _open(document.tobytes())
    first, addendum, second = (f.id for f in reading.asked)
    answer = _answer(
        [
            _field(first, "initials", "client", "Initials"),
            _field(addendum, "checkbox", "client", "Addendum applies"),
            _field(
                second,
                "initials",
                "client",
                "Initials",
                depends_on={"id": addendum, "option": "checked"},
            ),
        ],
        roles=[{"slug": "client", "kind": "signer"}],
    )
    result = derive(reading, answer, opened, problems=[], repaired=False)
    initials = next(f for f in result.fields if f.key == "client.initials")
    assert initials.ids == [first, second] and initials.depends_on is None
    assert initials.needs_review == (
        "its places do not all apply under the same option; check when it applies"
    )


def test_a_date_fields_format_is_kept_when_its_type_has_it_and_defaulted_when_not() -> None:
    reading, document = _open(forms.nda_like())
    ids = _ids(reading)

    def proposed(holds: str, fmt: str | None) -> dict[str, str | None]:
        answer = _nda_answer(reading)
        answer["fields"][0] = _field(ids["Governing Law"], holds, "sender", "Year", format=fmt)
        result = derive(reading, answer, document, problems=[], repaired=False)
        return {f.label: f.format for f in result.fields}

    assert proposed("year", "YY")["Year"] == "YY"  # a year after a printed "20"
    assert proposed("year", "Month")["Year"] == "YYYY"  # a month's format: the year's default
    assert proposed("date", None)["Year"] == "Month D, YYYY"  # none given: the default
    assert proposed("text", "YY")["Year"] is None  # text has no formats
    assert proposed("year", "YY")["MNDA term in years"] is None
