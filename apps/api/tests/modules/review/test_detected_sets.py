"""What detection stores, a Save takes back unchanged (Phase 6 LLD §2: the checks on a Save are
the shape of the data). The rules a Save applies and the ones detection writes by have one
definition (review.values), so a version nobody edited can always be saved."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from signora.kernel.db import Database
from signora.modules.review.values import OPTION_MAX
from tests.modules.documents.conftest import create_department, new_document
from tests.modules.review.test_approve import _approve
from tests.modules.review.test_revisions import _revise
from tests.modules.review.test_save import _body, _save, _view
from tests.support import forms
from tests.support.ai import FakeAssigner, Fields, plain_answer


def _detected(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    pdf: bytes,
    answer: Callable[[Fields], dict[str, Any]],
) -> tuple[str, str]:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf).json()
    version_id = document["versions"][0]["id"]
    run(version_id)
    detect(version_id, FakeAssigner(answer))
    return document["id"], version_id


def test_checkboxes_grouped_into_one_choice_are_saved_as_detection_stored_them(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    """Detection makes one choice of a PDF's checkboxes that are one question; each box keeps its
    kind and stands for an option. Save allowed a checkbox place to hold a checkbox only, so the
    untouched set was refused: "A checkbox box cannot hold this"."""

    def grouped(fields: Fields) -> dict[str, Any]:
        answer = plain_answer(fields)
        boxes = [field_id for field_id, kind in fields if kind == "checkbox"]
        answer["checkbox_groups"] = [{"ids": boxes, "label": "Client type"}]
        return answer

    document_id, version_id = _detected(owner, run, detect, forms.flat_marks(), grouped)
    view = _view(owner, document_id, version_id)
    group = next(f for f in view["fields"] if f["label"] == "Client type")
    assert group["holds"] == "choice"
    assert [(p["kind"], p["option_value"]) for p in group["placements"]] == [
        ("checkbox", "Individual"),
        ("checkbox", "Business entity"),
    ]

    assert _save(owner, document_id, version_id, _body(view)).status_code == 200

    # A PDF's checkbox that stands for no option is still only a checkbox.
    view = _view(owner, document_id, version_id)
    body = _body(view)
    lone = next(f for f in body["fields"] if f["label"] == "Client type")
    lone["places"] = [{**place, "option_value": None} for place in lone["places"]]
    refused = _save(owner, document_id, version_id, body)
    assert refused.status_code == 422
    assert {e["message"] for e in refused.json()["errors"]} >= {"A checkbox box cannot hold this"}


def test_an_option_as_long_as_detection_keeps_is_saved(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    """Detection keeps up to OPTION_MAX characters of an option's words; Save took 200, so a
    version with a longer option could never be saved."""
    document_id, version_id = _detected(owner, run, detect, forms.all_types(), plain_answer)
    words = ("the client elects the extended engagement " * 12)[:OPTION_MAX]
    with committing_db.unit_of_work() as uow:
        changed = uow.session.execute(
            text(
                "UPDATE field_placements SET option_text = :t "
                "WHERE version_id = :v AND option_value IS NOT NULL RETURNING id"
            ),
            {"t": words, "v": version_id},
        ).all()
    assert changed

    view = _view(owner, document_id, version_id)
    assert _save(owner, document_id, version_id, _body(view)).status_code == 200


def _conditioned_on_the_dropdown(fields: Fields) -> dict[str, Any]:
    """The first text box is asked only when the first dropdown is "Texas"."""
    answer = plain_answer(fields)
    dropdown = next(field_id for field_id, kind in fields if kind == "combobox")
    under = next(f for f in answer["fields"] if f["holds"] == "text")
    under["depends_on"] = {"id": dropdown, "option": "Texas"}
    return answer


def _dropdowns(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for f in view["fields"] for p in f["placements"] if p["kind"] == "combobox"]


def test_a_condition_on_a_dropdowns_option_is_saved_and_checked_against_its_options(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    """A dropdown is one place, so its options were kept nowhere in review: a condition detection
    stored on one ("only when the state is Texas") was refused on every Save. The options are
    kept with the place, as the PDF gives them."""
    document_id, version_id = _detected(
        owner, run, detect, forms.all_types(), _conditioned_on_the_dropdown
    )
    view = _view(owner, document_id, version_id)
    assert _dropdowns(view)[0]["options"] == ["California", "New York", "Texas"]
    under = next(f for f in view["fields"] if f["depends_on"])
    assert under["depends_on"]["option"] == "Texas"

    assert _save(owner, document_id, version_id, _body(view)).status_code == 200  # untouched

    # The options survive the Save (the editor never sends them: they are the PDF's) ...
    view = _view(owner, document_id, version_id)
    assert _dropdowns(view)[0]["options"] == ["California", "New York", "Texas"]
    # ... and an option the dropdown does not offer is still refused.
    body = _body(view)
    next(f for f in body["fields"] if f["depends_on"])["depends_on"]["option"] = "Ohio"
    refused = _save(owner, document_id, version_id, body)
    assert refused.status_code == 422
    assert [e["message"] for e in refused.json()["errors"]] == [
        "That option is not one of the field's"
    ]


def test_the_migration_fills_the_options_of_places_already_stored(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    """Places stored before the column take their options from their version's reading of the
    PDF: a version in review, an approved one (frozen: the trigger is off for the statement), and
    one made by editing, which has no reading of its own."""
    migration = importlib.import_module("signora.migrations.versions.0018a_dropdown_options")
    document_id, version_id = _detected(
        owner, run, detect, forms.all_types(), _conditioned_on_the_dropdown
    )
    assert _approve(owner, document_id, version_id).status_code == 204
    edited = _revise(owner, document_id, version_id, _body(_view(owner, document_id, version_id)))
    assert edited.status_code == 201, edited.text
    versions = [version_id, edited.json()["version_id"]]

    with committing_db.unit_of_work() as uow:  # as before the column: no options anywhere
        uow.session.execute(
            text(f"ALTER TABLE field_placements DISABLE TRIGGER {migration.FROZEN}")
        )
        uow.session.execute(
            text("UPDATE field_placements SET options = NULL WHERE version_id = ANY(:v)"),
            {"v": versions},
        )
        uow.session.execute(text(f"ALTER TABLE field_placements ENABLE TRIGGER {migration.FROZEN}"))
    assert all(
        place["options"] is None
        for v in versions
        for place in _dropdowns(_view(owner, document_id, v))
    )

    with committing_db.unit_of_work() as uow:
        for statement in migration.FILL:
            uow.session.execute(text(statement))

    for v in versions:
        assert _dropdowns(_view(owner, document_id, v))[0]["options"] == [
            "California",
            "New York",
            "Texas",
        ]
    # The trigger is back: an approved version's places are frozen again.
    with pytest.raises(DBAPIError), committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE field_placements SET options = NULL WHERE version_id = :v"),
            {"v": version_id},
        )
