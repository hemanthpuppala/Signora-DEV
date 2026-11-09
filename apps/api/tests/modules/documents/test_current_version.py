"""Which version is current, and stored versions never change (Phase 4 LLD §4.2-4.3; Phase 6 §1.1,
§1.3, §9.2): only an approved version can be current."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import sqlalchemy.exc
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.documents.conftest import (
    Account,
    add_version,
    create_department,
    csrf_headers,
    log_in,
    new_document,
)
from tests.support.files import pdf_bytes

DOCUMENTS = "/api/v1/documents"


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


def test_a_version_becomes_current_when_approved_not_when_ready(
    owner: TestClient,
    ready: Callable[..., None],
    approved: Callable[..., None],
    committing_db: Database,
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    version_id = _version_id(document, 1)

    ready(version_id)
    in_review = _document(owner, document["id"])
    assert in_review["current_version"] is None  # in review: nothing to send yet
    assert in_review["versions"][0]["status"] == "ready"

    approved(version_id)
    after = _document(owner, document["id"])
    assert after["current_version"]["number"] == 1
    assert after["versions"][0]["status"] == "approved"
    assert after["versions"][0]["approved"]["by"]["id"]  # who approved, and when
    assert after["versions"][0]["approved"]["at"]
    with committing_db.unit_of_work() as uow:
        actions = uow.session.execute(
            text(
                "SELECT action, data FROM audit_events WHERE subject_id = :d "
                "AND action IN ('document.version_approved', 'document.current_version_changed') "
                "ORDER BY seq"
            ),
            {"d": document["id"]},
        ).all()
    assert [a.action for a in actions] == [
        "document.version_approved",
        "document.current_version_changed",
    ]
    assert (actions[1].data["old"], actions[1].data["new"]) == (None, 1)


def test_the_newest_approved_takes_over_and_an_older_one_approved_later_never_does(
    owner: TestClient, ready: Callable[..., None], approved: Callable[..., None]
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(1)).json()
    approved(_version_id(document, 1))
    add_version(owner, document["id"], pdf_bytes(2), department["id"])
    added = add_version(owner, document["id"], pdf_bytes(3), department["id"]).json()
    ready(_version_id(added, 2))

    approved(_version_id(added, 3))
    approved(_version_id(added, 2))  # approved later, but older

    assert _document(owner, document["id"])["current_version"]["number"] == 3


def test_only_an_approved_version_can_be_made_current(
    owner: TestClient,
    ready: Callable[..., None],
    approved: Callable[..., None],
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(1)).json()
    approved(_version_id(document, 1))
    second = add_version(owner, document["id"], pdf_bytes(2), department["id"]).json()
    ready(_version_id(second, 2))

    refused = _make_current(owner, document["id"], _version_id(second, 2))
    assert (refused.status_code, refused.json()["code"]) == (409, "version-not-ready")

    approved(_version_id(second, 2))
    chosen = _make_current(owner, document["id"], _version_id(second, 1))
    again = _make_current(owner, document["id"], _version_id(second, 1))  # repeat-safe
    assert chosen.json()["current_version"]["number"] == 1
    assert again.status_code == 200
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert _make_current(theirs, document["id"], _version_id(second, 2)).status_code == 403

    third = add_version(owner, document["id"], pdf_bytes(3), department["id"]).json()
    approved(_version_id(third, 3))  # a newer approval takes over a choice
    assert _document(owner, document["id"])["current_version"]["number"] == 3


def test_an_approved_versions_fields_are_frozen_and_not_found_again(
    owner: TestClient, approved: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    version_id = _version_id(document, 1)
    approved(version_id)

    with pytest.raises(sqlalchemy.exc.DBAPIError), committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "INSERT INTO version_roles (workspace_id, version_id, slug, label, kind, position) "
                "SELECT workspace_id, id, 'client', 'Client', 'signer', 1 FROM document_versions "
                "WHERE id = :v"
            ),
            {"v": version_id},
        )
    again = owner.post(
        f"{DOCUMENTS}/{document['id']}/versions/{version_id}/detection",
        headers=csrf_headers(owner),
    )
    assert (again.status_code, again.json()["code"]) == (409, "fields-approved")


def test_stored_versions_never_change_in_the_database(
    owner: TestClient, ready: Callable[..., None], committing_db: Database
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    version_id = _version_id(document, 1)
    ready(version_id)

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
            text("UPDATE document_versions SET description = 'A letter' WHERE id = :id"),
            {"id": version_id},
        )
