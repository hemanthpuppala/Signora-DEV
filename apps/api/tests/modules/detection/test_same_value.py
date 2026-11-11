"""One value asked in many places (findings F11): fields the AI marks as the same value become one
field with every place, when they are one party's and hold the same kind of value."""

from __future__ import annotations

from typing import Any

import pymupdf
import pytest

from signora.modules.detection.derive import check, derive
from signora.modules.detection.read import read_document
from signora.modules.detection.schema import answer_model

U = "_" * 16
SENTENCE = f"by and between {U}, whose address is {U}, and the University."


def _page() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for y in (100, 200, 300):  # the same sentence printed three times
        page.insert_text((72, y), SENTENCE, fontsize=10)
    data: bytes = document.tobytes()
    return data


def _answer(ids: list[str], same: dict[str, str | None], **who: str) -> dict[str, Any]:
    """Names (even ids) and addresses (odd ids), each repeat pointing at ``same``'s choice."""
    fields = []
    for n, field_id in enumerate(ids):
        holds = "party_name" if n % 2 == 0 else "address"
        entry: dict[str, Any] = {
            "id": field_id,
            "holds": holds,
            "format": None,
            "filled_by": who.get(field_id, "client"),
            "label": "Name" if holds == "party_name" else "Address",
            "must_fill": True,
            "depends_on": None,
        }
        if same:
            entry["same_as"] = same.get(field_id)
        fields.append(entry)
    return {
        "roles": [
            {"slug": slug, "kind": "signer" if slug == "client" else "countersigner"}
            for slug in sorted({field["filled_by"] for field in fields})
        ],
        "fields": fields,
        "checkbox_groups": [],
        "extra_fields": [],
        "document": None,
    }


def _run(answer: dict[str, Any]) -> tuple[list[str], Any]:
    data = _page()
    reading = read_document(data)
    with pymupdf.open(stream=data, filetype="pdf") as document:
        problems = check(answer, reading, document)
        return problems, derive(reading, answer, document, problems=problems, repaired=True)


def _ids() -> list[str]:
    return [field.id for field in read_document(_page()).asked]


def test_the_schema_asks_for_same_as_on_every_field() -> None:
    schema = answer_model(["f1", "f2"]).model_json_schema()
    field = schema["$defs"]["FieldAnswer"]
    assert "same_as" in field["required"] and "same_as" in field["properties"]


def test_an_address_repeated_in_the_same_sentence_is_one_field_in_every_place() -> None:
    ids = _ids()  # f1 name, f2 address, f3 name, f4 address, f5 name, f6 address
    problems, result = _run(_answer(ids, {ids[3]: ids[1], ids[5]: ids[3]}))
    assert problems == []
    address = [field for field in result.fields if field.holds == "address"]
    assert (
        len(address) == 1 and len(address[0].placements) == 3 and address[0].key == "client.address"
    )


def test_without_same_as_the_repeats_stay_separate_as_before() -> None:
    ids = _ids()
    _, result = _run(_answer(ids, {}))  # an answer from before F11: no same_as key at all
    assert sum(1 for field in result.fields if field.holds == "address") == 3


@pytest.mark.parametrize(
    ("same", "who", "problem"),
    [
        pytest.param("other party", "firm", "not the same party's", id="another-party"),
        pytest.param("other kind", None, "not the same kind of value", id="another-kind"),
        pytest.param("itself", None, "the same value as itself", id="itself"),
    ],
)
def test_a_wrong_mark_is_a_problem_and_is_never_merged(
    same: str, who: str | None, problem: str
) -> None:
    ids = _ids()
    target = {"other party": ids[1], "other kind": ids[0], "itself": ids[3]}[same]
    by = {ids[1]: who} if who else {}
    problems, result = _run(_answer(ids, {ids[3]: target}, **by))
    assert any(problem in line for line in problems)
    assert sum(1 for field in result.fields if field.holds == "address") >= 2  # not merged
    assert any("same value" in note for note in result.notes)


def test_marks_that_loop_are_one_value_once() -> None:
    ids = _ids()
    problems, result = _run(_answer(ids, {ids[1]: ids[3], ids[3]: ids[1]}))
    assert sum(1 for field in result.fields if field.holds == "address") == 2  # f2+f4, and f6
    assert problems == []


def test_two_same_value_fields_at_one_position_are_keyed_without_error() -> None:
    """Review #6: two fields at the same position (duplicate widgets) made the group's first
    field and the key order disagree, and keying raised KeyError."""
    from signora.modules.detection.derive import PlacementOut, _Item, _keyed, _same_values

    def item(field_id: str) -> _Item:
        place = PlacementOut(page=1, rect=(10, 10, 100, 20), kind="text")
        return _Item(
            ids=[field_id],
            label="Address",
            holds="address",
            filled_by="party_1",
            required=True,
            placements=[place],
            order=(1, 10.0, 10.0),
            review=[],
        )

    items = {"f1": item("f1"), "f2": item("f2")}
    answer = {
        "fields": [
            {"id": "f1", "filled_by": "party_1", "holds": "address", "same_as": "f2"},
            {"id": "f2", "filled_by": "party_1", "holds": "address", "same_as": None},
        ]
    }
    _same_values(answer, items, [])
    (field,) = _keyed(items)
    assert field.ids == ["f1", "f2"] and len(field.placements) == 2
