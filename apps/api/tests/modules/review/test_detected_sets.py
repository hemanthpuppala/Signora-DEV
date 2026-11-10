"""What detection stores, a Save takes back unchanged (Phase 6 LLD §2: the checks on a Save are
the shape of the data). The rules a Save applies and the ones detection writes by have one
definition (review.values), so a version nobody edited can always be saved."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from signora.modules.review.values import OPTION_MAX
from tests.modules.documents.conftest import create_department, new_document
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
