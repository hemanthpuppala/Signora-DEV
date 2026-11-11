"""Detection's API (Phase 5 LLD §1.3, §5.4): running it by hand and reading a version's fields."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from signora.modules.detection.ai import AiError
from tests.modules.detection.conftest import KIND
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


def _run_id(db: Database, version_id: str) -> str:
    with db.unit_of_work() as uow:
        return str(
            uow.session.execute(
                text("SELECT run_id FROM detection_runs WHERE version_id = :v"), {"v": version_id}
            ).scalar_one()
        )


def _queued(db: Database, version_id: str) -> int:
    """Detection jobs waiting for this version (each request is its own)."""
    with db.unit_of_work() as uow:
        return int(
            uow.session.execute(
                text(
                    "SELECT count(*) FROM jobs WHERE kind = :k AND status = 'queued' "
                    "AND payload->>'version_id' = :v"
                ),
                {"k": KIND, "v": version_id},
            ).scalar_one()
        )


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
    assert view["flags"]["name_dropped"] is False  # F6: reported with the version's flags
    # Phase 6: ids for editing, the revision a Save starts from, and the warnings before Approve.
    party = {r["slug"]: r["id"] for r in view["roles"]}
    signed = [f for f in view["fields"] if f["holds"] == "signature"]
    assert {f["party_id"] for f in signed} == {party["party_1"], party["party_2"]}
    assert all(p["id"] for f in view["fields"] for p in f["placements"])
    assert view["revision"] == 0
    assert "party_cannot_sign" not in {w["code"] for w in view["warnings"]}  # both can sign


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


def test_detection_resumes_after_each_failure_until_it_finishes(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _processed(owner, run)

    # Failing and resuming twice: each resume is its own job (review fix: a reused job key once
    # dropped the second one, leaving the version "Finding fields" for good).
    for _ in range(2):
        detect(version_id, FakeAssigner(AiError("ai_not_configured", "no key")))
        assert _fields(owner, document_id, version_id)["status"] == "failed"
        run_id = _run_id(committing_db, version_id)
        queued = _queued(committing_db, version_id)
        resumed = _run_by_hand(owner, document_id, version_id)
        assert (resumed.status_code, resumed.json()) == (202, {"mode": "resume"})
        assert _run_by_hand(owner, document_id, version_id).json() == {"mode": "running"}
        assert _queued(committing_db, version_id) == queued + 1  # one job, not one per click
        assert _run_id(committing_db, version_id) == run_id  # the same run, where it stopped
    detect(version_id, FakeAssigner())
    view = _fields(owner, document_id, version_id)
    assert (view["status"], view["found_again_failed"]) == ("ready", None)


def test_finding_fields_again_restarts_and_a_failure_keeps_the_fields_found_before(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _processed(owner, run)
    detect(version_id, FakeAssigner())
    before = _fields(owner, document_id, version_id)
    first_run = _run_id(committing_db, version_id)

    again = _run_by_hand(owner, document_id, version_id)
    assert (again.status_code, again.json()) == (202, {"mode": "restart"})
    assert _run_id(committing_db, version_id) != first_run
    assert _fields(owner, document_id, version_id)["stage"] == "read"  # a new run from the start

    # Review fix: a failed second look once left the version "failed" (no viewer, and a current
    # version that was not ready). It is ready again, with the fields found before.
    detect(version_id, FakeAssigner(AiError("ai_not_configured", "no key")))
    after = _fields(owner, document_id, version_id)
    assert after["status"] == "ready"
    assert after["found_again_failed"] == "Field detection isn't set up yet"
    assert (after["fields"], after["roles"], after["flags"]) == (
        before["fields"],
        before["roles"],
        before["flags"],
    )
    document = owner.get(f"{DOCUMENTS}/{document_id}").json()
    assert document["versions"][0]["status"] == "ready"

    assert _run_by_hand(owner, document_id, version_id).json() == {"mode": "restart"}
    detect(version_id, FakeAssigner())
    assert _fields(owner, document_id, version_id)["found_again_failed"] is None


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
