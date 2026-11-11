"""How a field writes a date or a part of one, saved and read with the field (Phase 7c LLD)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.modules.review.test_save import _body, _drawn, _in_review, _save, _view


def test_a_date_field_keeps_its_format_and_refuses_another_types(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    body = _body(_view(owner, document_id, version_id))
    year = {**_drawn("Year", None, holds="year", rect=[300, 40, 330, 60]), "format": "YY"}
    when = _drawn("Effective date", None, holds="date", rect=[300, 80, 420, 100])  # no format
    note = _drawn("Note", None, rect=[300, 120, 420, 140])
    body["fields"] += [year, when, note]
    assert _save(owner, document_id, version_id, body).status_code == 200

    fields = {f["label"]: f for f in _view(owner, document_id, version_id)["fields"]}
    assert fields["Year"]["format"] == "YY"
    assert fields["Effective date"]["format"] == "Month D, YYYY"  # the type's default
    assert fields["Note"]["format"] is None  # text is written as typed

    body = _body(_view(owner, document_id, version_id))
    assert _save(owner, document_id, version_id, body).status_code == 200  # saved as read
    assert (
        next(f for f in _view(owner, document_id, version_id)["fields"] if f["label"] == "Year")[
            "format"
        ]
        == "YY"
    )
    body = _body(_view(owner, document_id, version_id))
    at = next(i for i, f in enumerate(body["fields"]) if f["label"] == "Year")
    body["fields"][at]["format"] = "Month"  # a month's format on a year
    refused = _save(owner, document_id, version_id, body)
    assert refused.status_code == 422
    assert {(e["field"], e["message"]) for e in refused.json()["errors"]} == {
        (f"fields[{at}].format", "Choose one of this type's formats")
    }
