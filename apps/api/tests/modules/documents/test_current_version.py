"""Which version is current, and stored versions never change (Phase 4 LLD §4.2-4.3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import sqlalchemy.exc
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from signora.modules.documents import processing
from signora.modules.documents.conversion import ConversionUnavailableError
from tests.modules.documents.conftest import (
    Account,
    add_version,
    create_department,
    csrf_headers,
    log_in,
    new_document,
)
from tests.support.files import docx_bytes, pdf_bytes, pdf_with_scan

DOCUMENTS = "/api/v1/documents"
UNREACHABLE = "http://127.0.0.1:9"  # nothing listens: a passing outage


def _document(api: TestClient, document_id: str) -> Any:
    return api.get(f"{DOCUMENTS}/{document_id}").json()


def _make_current(api: TestClient, document_id: str, version_id: str) -> Any:
    return api.post(
        f"{DOCUMENTS}/{document_id}/current-version",
        json={"version_id": version_id},
        headers=csrf_headers(api),
    )


def _version_id(document: Any, number: int) -> str:
    return str(next(v["id"] for v in document["versions"] if v["number"] == number))


def test_the_first_ready_version_becomes_current(
    owner: TestClient, run: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    assert document["current_version"] is None

    run(_version_id(document, 1))

    after = _document(owner, document["id"])
    assert after["current_version"]["number"] == 1
    assert after["versions"][0]["is_current"] is True
    with committing_db.unit_of_work() as uow:
        data = uow.session.execute(
            text(
                "SELECT data FROM audit_events WHERE action = 'document.current_version_changed' "
                "AND subject_id = :d"
            ),
            {"d": document["id"]},
        ).scalar_one()
    assert (data["old"], data["new"], data["automatic"]) == (None, 1, True)


def test_the_latest_takes_over_when_ready_and_a_slower_older_one_never_does(
    owner: TestClient, run: Callable[..., None]
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(1)).json()
    run(_version_id(document, 1))
    add_version(owner, document["id"], pdf_bytes(2), department["id"])
    added = add_version(owner, document["id"], pdf_bytes(3), department["id"]).json()

    assert added["current_version"]["number"] == 1  # versions 2 and 3 still processing
    run(_version_id(added, 3))
    run(_version_id(added, 2))  # finishes later, but is older

    assert _document(owner, document["id"])["current_version"]["number"] == 3


def test_a_version_that_is_not_ready_never_becomes_current(
    owner: TestClient, run: Callable[..., None]
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(1)).json()
    run(_version_id(document, 1))
    added = add_version(owner, document["id"], pdf_with_scan([1]), department["id"]).json()
    run(_version_id(added, 2))

    after = _document(owner, document["id"])
    assert after["current_version"]["number"] == 1
    refused = _make_current(owner, document["id"], _version_id(added, 2))
    assert (refused.status_code, refused.json()["code"]) == (409, "version-not-ready")


def test_an_older_version_ready_after_try_again_never_overrides_a_choice(
    owner: TestClient, run: Callable[..., None]
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(1)).json()
    run(_version_id(document, 1))
    add_version(owner, document["id"], docx_bytes(), department["id"])
    added = add_version(owner, document["id"], pdf_bytes(3), department["id"]).json()
    second = _version_id(added, 2)
    with pytest.raises(ConversionUnavailableError):  # version 2 fails for good: Try again offered
        run(second, attempt=processing.MAX_ATTEMPTS, gotenberg_url=UNREACHABLE)
    run(_version_id(added, 3))
    _make_current(owner, document["id"], _version_id(added, 1))  # a person picks version 1

    retried = owner.post(
        f"{DOCUMENTS}/{document['id']}/versions/{second}/retry", headers=csrf_headers(owner)
    )
    assert retried.status_code == 200, retried.text
    run(second)

    after = _document(owner, document["id"])
    assert next(v for v in after["versions"] if v["number"] == 2)["status"] == "processed"
    assert after["current_version"]["number"] == 1


def test_any_ready_version_can_be_made_current_until_a_newer_one_is_ready(
    owner: TestClient,
    run: Callable[..., None],
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(1)).json()
    run(_version_id(document, 1))
    second = add_version(owner, document["id"], pdf_bytes(2), department["id"]).json()
    run(_version_id(second, 2))

    chosen = _make_current(owner, document["id"], _version_id(second, 1))
    again = _make_current(owner, document["id"], _version_id(second, 1))  # repeat-safe

    assert chosen.json()["current_version"]["number"] == 1
    assert again.status_code == 200
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert _make_current(theirs, document["id"], _version_id(second, 2)).status_code == 403
    third = add_version(owner, document["id"], pdf_bytes(3), department["id"]).json()
    run(_version_id(third, 3))
    assert _document(owner, document["id"])["current_version"]["number"] == 3


def test_stored_versions_never_change_in_the_database(
    owner: TestClient, run: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    version_id = _version_id(document, 1)
    run(version_id)

    for statement in (
        "UPDATE document_versions SET source_sha256 = repeat('0', 64) WHERE id = :id",
        "UPDATE document_versions SET page_count = 99 WHERE id = :id",
        "UPDATE document_versions SET pdf_sha256 = repeat('1', 64) WHERE id = :id",
        "DELETE FROM document_versions WHERE id = :id",
    ):
        with pytest.raises(sqlalchemy.exc.DBAPIError), committing_db.unit_of_work() as uow:
            uow.session.execute(text(statement), {"id": version_id})
    with committing_db.unit_of_work() as uow:  # what may change still can
        uow.session.execute(
            text("UPDATE document_versions SET ai_description = 'A letter' WHERE id = :id"),
            {"id": version_id},
        )
