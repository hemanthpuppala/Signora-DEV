"""A version's life after processing, as detection drives it (Phase 5 LLD §1.1-1.3)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from signora.kernel.db import Database
from signora.modules.documents import lifecycle
from tests.modules.documents.conftest import create_department, csrf_headers, new_document
from tests.support.files import pdf_bytes

DOCUMENTS = "/api/v1/documents"


def _version(api: TestClient, document_id: str) -> Any:
    return api.get(f"{DOCUMENTS}/{document_id}").json()["versions"][0]


def _facts(db: Database, version_id: str) -> lifecycle.VersionForDetection:
    with db.unit_of_work() as uow:
        found = lifecycle.version_for_detection(uow.session, uuid.UUID(version_id))
    assert found is not None
    return found


def test_processing_leaves_a_version_detecting_and_detection_makes_it_ready_for_review(
    owner: TestClient, run: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(2)).json()
    version_id = document["versions"][0]["id"]
    run(version_id)
    assert _version(owner, document["id"])["status"] == "detecting"
    facts = _facts(committing_db, version_id)
    assert facts.source.sha256 != ""  # the original PDF, read by detection (§2.1)
    assert _version(owner, document["id"])["name"] is None  # named once its fields are found

    named = {"name": "Mutual NDA", "description": "A mutual NDA between two parties."}
    with committing_db.unit_of_work() as uow:
        assert lifecycle.finish_detection(uow, facts, field_count=7, **named)
    with committing_db.unit_of_work() as uow:
        assert not lifecycle.finish_detection(uow, facts, field_count=7, **named)  # once only

    after = owner.get(f"{DOCUMENTS}/{document['id']}").json()
    assert (after["versions"][0]["status"], after["versions"][0]["field_count"]) == ("ready", 7)
    assert {k: after["versions"][0][k] for k in named} == named  # the version keeps the AI's words
    assert after["current_version"] is None  # in review: current once approved (Phase 6 §1.3)
    assert after["latest_version"]["field_count"] == 7


def test_a_detection_failure_offers_try_again_which_detects_again(
    owner: TestClient, run: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    version_id = document["versions"][0]["id"]
    run(version_id)
    with committing_db.unit_of_work() as uow:
        lifecycle.fail_detection(uow, _facts(committing_db, version_id), "ai_unavailable")

    problem = _version(owner, document["id"])["problem"]
    assert problem == {
        "code": "ai_unavailable",
        "message": "Field detection couldn't reach the AI",
        "can_retry": True,
    }
    retried = owner.post(
        f"{DOCUMENTS}/{document['id']}/versions/{version_id}/retry", headers=csrf_headers(owner)
    )
    assert retried.status_code == 200, retried.text
    assert _version(owner, document["id"])["status"] == "detecting"


def test_the_ai_names_and_describes_a_document_once_and_never_over_a_person(
    owner: TestClient, run: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    taken = new_document(owner, department["id"], pdf_bytes(1), name="Engagement letter").json()
    document = new_document(owner, department["id"], pdf_bytes(2), name="scan_0042").json()
    version_id = document["versions"][0]["id"]
    run(version_id)
    facts = _facts(committing_db, version_id)

    with committing_db.unit_of_work() as uow:  # a taken name keeps the current one
        lifecycle.apply_name_and_description(
            uow, facts, name="  Engagement   letter ", description="A short description."
        )
    named = owner.get(f"{DOCUMENTS}/{document['id']}").json()
    assert (named["name"], named["description"]) == ("scan_0042", "A short description.")

    with committing_db.unit_of_work() as uow:  # written once: the description is the AI's now
        lifecycle.apply_name_and_description(
            uow, facts, name="Mutual NDA", description="Another description."
        )
    after = owner.get(f"{DOCUMENTS}/{document['id']}").json()
    assert (after["name"], after["description"]) == ("Mutual NDA", "A short description.")
    assert taken["name"] == "Engagement letter"
