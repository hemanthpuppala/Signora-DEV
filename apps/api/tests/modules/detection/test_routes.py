"""Detection's API (Phase 5 LLD §1.3, §5.4): running it by hand and reading a version's fields."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from signora.modules.detection.ai import AiError
from signora.modules.detection.jobs import RUN
from tests.modules.documents.conftest import create_department, csrf_headers, new_document
from tests.modules.identity_access.conftest import Account, log_in
from tests.support import forms
from tests.support.ai import FakeAssigner, plain_answer

DOCUMENTS = "/api/v1/documents"


def _processed(owner: TestClient, run: Callable[..., None]) -> tuple[str, str]:
    department = create_department(owner)
    document = new_document(owner, department["id"], forms.nda_like()).json()
    version_id = document["versions"][0]["id"]
    run(version_id)
    return document["id"], version_id


def _run_by_hand(api: TestClient, document_id: str, version_id: str) -> Any:
    return api.post(
        f"{DOCUMENTS}/{document_id}/versions/{version_id}/detection", headers=csrf_headers(api)
    )


def _fields(api: TestClient, document_id: str, version_id: str) -> Any:
    response = api.get(f"{DOCUMENTS}/{document_id}/versions/{version_id}/fields")
    assert response.status_code == 200, response.text
    return response.json()


def _queued_run(db: Database, version_id: str) -> str:
    with db.unit_of_work() as uow:
        payload = uow.session.execute(
            text(
                "SELECT payload FROM jobs WHERE kind = :k AND payload->>'version_id' = :v "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"k": RUN, "v": version_id},
        ).scalar_one()
    return str(payload["run_id"])


def test_a_ready_versions_fields_with_their_roles_places_and_dependencies(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    document_id, version_id = _processed(owner, run)

    def with_parties(fields: list[tuple[str, str]]) -> dict[str, Any]:
        answer = plain_answer(fields)
        kinds = dict(fields)
        signatures = [i for i, k in fields if k == "signature"]
        answer["roles"] = [
            {"slug": "party_1", "kind": "signer"},
            {"slug": "party_2", "kind": "signer"},
        ]
        for item in answer["fields"]:
            if kinds[item["id"]] == "signature":
                item["filled_by"] = "party_1" if item["id"] == signatures[0] else "party_2"
        return answer

    detect(version_id, FakeAssigner(with_parties))
    view = _fields(owner, document_id, version_id)

    assert (view["status"], view["stage"], view["fields_from"]) == ("ready", "done", "form_fields")
    assert [(r["slug"], r["label"], r["position"], r["field_count"]) for r in view["roles"]] == [
        ("party_1", "Party 1", 1, 1),
        ("party_2", "Party 2", 2, 1),
    ]
    choice = next(f for f in view["fields"] if f["holds"] == "choice")
    assert [p["option_text"] for p in choice["placements"]] == [
        "Expires … from Effective Date.",  # the term's blank inside its words
        "Continues until terminated.",
    ]
    term = next(f for f in view["fields"] if f["depends_on"] is not None)
    assert term["depends_on"] == {"key": choice["key"], "option": "True"}
    assert all(f["placements"] for f in view["fields"])
    assert view["pending"] == [] and view["flags"]["no_fields"] is False


def test_the_places_found_show_while_the_ai_works(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    document_id, version_id = _processed(owner, run)
    assert _fields(owner, document_id, version_id)["pending"] == []  # not read yet
    with pytest.raises(AiError):
        detect(version_id, FakeAssigner(AiError("ai_unavailable", "RateLimitError")))

    view = _fields(owner, document_id, version_id)
    assert (view["status"], view["stage"], view["fields"]) == ("detecting", "ai", [])
    assert [p["id"] for p in view["pending"]] == [f"f{n}" for n in range(1, 8)]
    assert all(len(p["placements"][0]["rect"]) == 4 for p in view["pending"])


def test_detection_runs_again_by_hand_and_resumes_after_a_failure(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _processed(owner, run)
    detect(version_id, FakeAssigner())

    again = _run_by_hand(owner, document_id, version_id)
    assert (again.status_code, again.json()) == (202, {"mode": "restart"})
    assert _run_by_hand(owner, document_id, version_id).json() == {"mode": "running"}
    run_id = _queued_run(committing_db, version_id)
    assert _fields(owner, document_id, version_id)["stage"] == "read"  # a new run from the start

    detect(version_id, FakeAssigner(AiError("ai_not_configured", "no key")), run_id=run_id)
    resumed = _run_by_hand(owner, document_id, version_id)
    assert (resumed.status_code, resumed.json()) == (202, {"mode": "resume"})
    assert _queued_run(committing_db, version_id) == run_id  # the same run, where it stopped
    detect(version_id, FakeAssigner(), run_id=run_id)
    assert _fields(owner, document_id, version_id)["status"] == "ready"


def test_detection_is_refused_before_processing_and_to_read_only_members(
    owner: TestClient,
    run: Callable[..., None],
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], forms.nda_like()).json()
    version_id = document["versions"][0]["id"]
    early = _run_by_hand(owner, document["id"], version_id)
    assert (early.status_code, early.json()["code"]) == (409, "version-not-processed")
    view = _fields(owner, document["id"], version_id)
    assert (view["status"], view["stage"]) == ("processing", None)

    run(version_id)
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert _run_by_hand(theirs, document["id"], version_id).status_code == 403
        assert _fields(theirs, document["id"], version_id)["status"] == "detecting"


def test_another_companys_version_is_not_found(
    owner: TestClient,
    run: Callable[..., None],
    make_client: Callable[..., TestClient],
    make_workspace: Callable[..., Account],
) -> None:
    document_id, version_id = _processed(owner, run)
    other = make_workspace()
    with make_client() as theirs:
        log_in(theirs, other.email)
        response = theirs.get(f"{DOCUMENTS}/{document_id}/versions/{version_id}/fields")
        assert response.status_code == 404
        assert _run_by_hand(theirs, document_id, version_id).status_code == 404
