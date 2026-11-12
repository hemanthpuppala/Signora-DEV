"""Processing a version in the background (Phase 4 LLD topic 3)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.blobstore import LocalBlobStore
from signora.kernel.db import Database
from signora.kernel.jobs import JobRegistry
from signora.kernel.jobs.core import reclaim_expired
from signora.modules.documents import jobs, processing
from signora.modules.documents.conversion import ConversionUnavailableError
from tests.modules.documents.conftest import (
    add_version,
    create_department,
    csrf_headers,
    new_document,
)
from tests.support.files import (
    docx_bytes,
    encrypted_pdf,
    pdf_bytes,
    pdf_with_scan,
)

DOCUMENTS = "/api/v1/documents"
UNREACHABLE = "http://127.0.0.1:9"  # nothing listens: a passing outage


def _version(api: TestClient, document_id: str) -> Any:
    return api.get(f"{DOCUMENTS}/{document_id}").json()["versions"][0]


def _queued(db: Database, version_id: str) -> int:
    with db.unit_of_work() as uow:
        return int(
            uow.session.execute(
                text(
                    "SELECT count(*) FROM jobs WHERE kind = 'document.process' "
                    "AND status = 'queued' AND payload->>'version_id' = :v"
                ),
                {"v": version_id},
            ).scalar_one()
        )


def test_creating_a_document_queues_its_processing(
    owner: TestClient, committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    assert _queued(committing_db, document["versions"][0]["id"]) == 1


def test_a_pdf_is_processed_into_a_working_copy_with_its_page_facts(
    owner: TestClient, run: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(3)).json()
    version_id = document["versions"][0]["id"]

    run(version_id)
    run(version_id)  # repeat-safe: a version past processing is left alone

    version = _version(owner, document["id"])
    assert (version["status"], version["page_count"], version["problem"]) == ("detecting", 3, None)
    assert version["pages"][2] == {"width": 595.0, "height": 842.0, "rotation": 0}
    with committing_db.unit_of_work() as uow:
        row = uow.session.execute(
            text("SELECT pdf_sha256, pages FROM document_versions WHERE id = :id"),
            {"id": version_id},
        ).one()
    assert row.pdf_sha256 is not None
    assert row.pages[0] == {"width": 595.0, "height": 842.0, "rotation": 0}


def test_a_word_file_is_converted_by_gotenberg(owner: TestClient, run: Callable[..., None]) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], docx_bytes()).json()

    run(document["versions"][0]["id"])

    version = _version(owner, document["id"])
    assert (version["status"], version["kind"], version["page_count"]) == ("detecting", "docx", 1)


def test_scanned_pages_go_on_to_detection_and_are_recorded(
    owner: TestClient, run: Callable[..., None]
) -> None:
    """Phase 5c: a scanned page no longer stops the version; detection reads it from its picture."""
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_with_scan([2, 3, 4, 7], pages=8)).json()

    run(document["versions"][0]["id"])

    version = _version(owner, document["id"])
    assert version["status"] == "detecting"
    assert version["pages_without_text"] == [2, 3, 4, 7]
    assert version["problem"] is None


def test_too_many_pages_fail_with_the_count(
    owner: TestClient, run: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(201)).json()

    run(document["versions"][0]["id"])

    problem = _version(owner, document["id"])["problem"]
    assert problem == {
        "code": "too_many_pages",
        "message": "This document has 201 pages. Upload one with 200 or fewer",
        "can_retry": False,
    }
    retry = owner.post(
        f"{DOCUMENTS}/{document['id']}/versions/{document['versions'][0]['id']}/retry",
        headers=csrf_headers(owner),
    )
    assert retry.json()["code"] == "cannot-retry"


def test_a_passing_outage_retries_then_fails_with_try_again(
    owner: TestClient, run: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], docx_bytes()).json()
    version_id = document["versions"][0]["id"]

    with pytest.raises(ConversionUnavailableError):  # the worker retries it
        run(version_id, attempt=1, gotenberg_url=UNREACHABLE)
    assert _version(owner, document["id"])["status"] == "processing"
    with pytest.raises(ConversionUnavailableError):  # the last attempt: the job dies
        run(version_id, attempt=processing.MAX_ATTEMPTS, gotenberg_url=UNREACHABLE)

    problem = _version(owner, document["id"])["problem"]
    assert (problem["code"], problem["can_retry"]) == ("unavailable", True)
    retried = owner.post(
        f"{DOCUMENTS}/{document['id']}/versions/{version_id}/retry", headers=csrf_headers(owner)
    )
    assert retried.json()["versions"][0]["status"] == "processing"
    assert _queued(committing_db, version_id) >= 1
    run(version_id)
    assert _version(owner, document["id"])["status"] == "detecting"


def test_a_failure_while_saving_on_the_last_attempt_offers_try_again(
    owner: TestClient, run: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()

    def broken_put(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(LocalBlobStore, "put", broken_put)
    with pytest.raises(OSError, match="disk full"):
        run(document["versions"][0]["id"], attempt=processing.MAX_ATTEMPTS)

    version = _version(owner, document["id"])
    assert version["status"] == "failed"
    assert (version["problem"]["code"], version["problem"]["can_retry"]) == ("unavailable", True)


def test_a_worker_that_dies_on_the_last_attempt_leaves_try_again(
    owner: TestClient, committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    version_id = document["versions"][0]["id"]
    registry = JobRegistry()
    jobs.register(registry)
    with committing_db.unit_of_work() as uow:  # the queued job was claimed 8 times; its worker died
        uow.session.execute(
            text(
                "UPDATE jobs SET status = 'running', attempts = :max, "
                "lease_expires_at = now() - interval '1 second' "
                "WHERE kind = 'document.process' AND payload->>'version_id' = :v"
            ),
            {"max": processing.MAX_ATTEMPTS, "v": version_id},
        )
    with committing_db.unit_of_work() as uow:
        _, dead = reclaim_expired(uow.session, registry)

    assert dead >= 1
    version = _version(owner, document["id"])
    assert version["status"] == "failed"
    assert (version["problem"]["code"], version["problem"]["can_retry"]) == ("unavailable", True)


def test_a_password_protected_pdf_is_unlocked_and_processing_continues(
    owner: TestClient, run: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], encrypted_pdf("open-sesame")).json()
    version_id = document["versions"][0]["id"]
    run(version_id)
    assert _version(owner, document["id"])["status"] == "needs_password"
    url = f"{DOCUMENTS}/{document['id']}/versions/{version_id}/unlock"

    wrong = owner.post(url, json={"password": "nope"}, headers=csrf_headers(owner))
    assert (wrong.status_code, wrong.json()["title"]) == (422, "Wrong password")
    right = owner.post(url, json={"password": "open-sesame"}, headers=csrf_headers(owner))
    assert right.status_code == 200, right.text
    assert right.json()["versions"][0]["status"] == "processing"
    run(version_id)

    assert _version(owner, document["id"])["status"] == "detecting"
    with committing_db.unit_of_work() as uow:
        data = uow.session.execute(
            text(
                "SELECT data::text FROM audit_events WHERE action = 'document.version_unlocked' "
                "AND subject_id = :d"
            ),
            {"d": document["id"]},
        ).scalar_one()
    assert "open-sesame" not in data


def test_five_wrong_passwords_make_the_next_try_wait(
    owner: TestClient, run: Callable[..., None]
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], encrypted_pdf("open-sesame")).json()
    version_id = document["versions"][0]["id"]
    run(version_id)
    url = f"{DOCUMENTS}/{document['id']}/versions/{version_id}/unlock"

    statuses = [
        owner.post(url, json={"password": f"guess-{n}"}, headers=csrf_headers(owner)).status_code
        for n in range(6)
    ]

    assert statuses == [422, 422, 422, 422, 422, 429]


def test_unlocking_a_version_that_needs_no_password_is_refused(
    owner: TestClient, run: Callable[..., None]
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    version_id = document["versions"][0]["id"]
    run(version_id)
    refused = owner.post(
        f"{DOCUMENTS}/{document['id']}/versions/{version_id}/unlock",
        json={"password": "x"},
        headers=csrf_headers(owner),
    )
    assert refused.json()["code"] == "version-not-locked"


def test_adding_a_version_queues_its_own_processing(
    owner: TestClient, committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(1)).json()
    added = add_version(owner, document["id"], pdf_bytes(2), department["id"]).json()
    assert _queued(committing_db, added["versions"][0]["id"]) == 1
    assert uuid.UUID(added["versions"][0]["id"])
