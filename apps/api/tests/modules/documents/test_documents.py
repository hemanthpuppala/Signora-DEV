"""Documents and versions (Phase 4 LLD topics 1, 2 and 4)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.documents.conftest import (
    DEPARTMENTS,
    Account,
    add_version,
    create_department,
    csrf_headers,
    idempotency_key,
    log_in,
    new_document,
    upload,
)
from tests.support.files import docx_bytes, pdf_bytes

DOCUMENTS = "/api/v1/documents"


def _create(api: TestClient, department_id: str, upload_id: str, **body: Any) -> Any:
    return api.post(
        f"{DEPARTMENTS}/{department_id}/documents",
        json={"name": "Engagement letter", "upload_id": upload_id, **body},
        headers={**csrf_headers(api), **idempotency_key()},
    )


def _actions(db: Database, document_id: str) -> list[str]:
    with db.unit_of_work() as uow:
        return list(
            uow.session.execute(
                text(
                    "SELECT action FROM audit_events WHERE subject_type = 'document' "
                    "AND subject_id = :d ORDER BY seq"
                ),
                {"d": document_id},
            ).scalars()
        )


def test_an_upload_becomes_a_document_with_its_first_version_processing(
    owner: TestClient, committing_db: Database
) -> None:
    department = create_department(owner)

    response = new_document(owner, department["id"], pdf_bytes(2), name="  Engagement   letter ")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Engagement letter"
    assert (body["access"], body["description"]) == ("edit", "")
    assert "require_email_code" not in body  # a send's setting (Phase 7 §4)
    assert body["current_version"] is None  # not ready yet (topic 4)
    assert body["latest_version"]["number"] == 1
    assert body["latest_version"]["status"] == "processing"
    [version] = body["versions"]
    assert (version["number"], version["status"], version["kind"]) == (1, "processing", "pdf")
    assert version["filename"] == "Letter.pdf"
    assert _actions(committing_db, body["id"]) == ["document.created", "document.version_added"]
    listed = owner.get(f"{DEPARTMENTS}/{department['id']}/documents").json()
    assert [d["id"] for d in listed] == [body["id"]]


def test_an_upload_is_used_once_by_its_own_uploader_in_its_own_department(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
    committing_db: Database,
) -> None:
    finance, hr = create_department(owner), create_department(owner, "HR")
    upload_id = upload(owner, finance["id"], pdf_bytes()).json()["id"]

    assert _create(owner, hr["id"], upload_id).json()["code"] == "upload-not-found"
    editor = add_member(company, role="read_write")
    with make_client() as theirs:
        log_in(theirs, editor.email)
        assert _create(theirs, finance["id"], upload_id).status_code == 404
    assert _create(owner, finance["id"], upload_id).status_code == 201
    assert _create(owner, finance["id"], upload_id, name="Other").json()["code"] == "upload-used"

    expired = upload(owner, finance["id"], docx_bytes()).json()["id"]
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE uploads SET expires_at = now() - interval '1 second' WHERE id = :id"),
            {"id": expired},
        )
    assert _create(owner, finance["id"], expired, name="Late").status_code == 404


def test_names_are_unique_per_department_ignoring_case(owner: TestClient) -> None:
    finance, hr = create_department(owner), create_department(owner, "HR")
    assert new_document(owner, finance["id"], pdf_bytes(1), name="NDA").status_code == 201

    taken = new_document(owner, finance["id"], pdf_bytes(2), name="nda")

    assert taken.status_code == 409
    assert taken.json()["code"] == "document-name-taken"
    assert new_document(owner, hr["id"], pdf_bytes(3), name="NDA").status_code == 201


def test_the_same_file_twice_in_a_department_asks_and_never_becomes_a_version(
    owner: TestClient,
) -> None:
    finance, hr = create_department(owner), create_department(owner, "HR")
    data = pdf_bytes(3)
    first = new_document(owner, finance["id"], data).json()

    again = upload(owner, finance["id"], data).json()

    assert again["duplicate"] == {
        "document_id": first["id"],
        "document_name": "Engagement letter",
        "version_number": 1,
        "archived": False,
    }
    refused = _create(owner, finance["id"], again["id"], name="Copy")
    assert (refused.status_code, refused.json()["code"]) == (409, "duplicate-file")
    assert "Engagement letter, version 1" in refused.json()["detail"]
    as_version = add_version(owner, first["id"], data, finance["id"])
    assert as_version.json()["code"] == "duplicate-file"
    separate = _create(
        owner,
        finance["id"],
        upload(owner, finance["id"], data).json()["id"],
        name="Copy",
        allow_duplicate=True,
    )
    assert separate.status_code == 201
    assert upload(owner, hr["id"], data).json()["duplicate"] is None  # other departments: no


def test_versions_are_numbered_in_upload_order(owner: TestClient) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(1)).json()

    second = add_version(owner, document["id"], pdf_bytes(2), department["id"])
    third = add_version(owner, document["id"], docx_bytes(), department["id"])

    assert second.status_code == 201, second.text
    numbers = [v["number"] for v in third.json()["versions"]]
    assert numbers == [3, 2, 1]
    assert third.json()["versions"][0]["kind"] == "docx"


def test_people_rename_and_describe(owner: TestClient, committing_db: Database) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()

    changed = owner.patch(
        f"{DOCUMENTS}/{document['id']}",
        json={
            "name": "Retainer",
            "description": "Signed before work starts",
        },
        headers=csrf_headers(owner),
    )

    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert (body["name"], body["description"]) == ("Retainer", "Signed before work starts")
    with committing_db.unit_of_work() as uow:
        sources = uow.session.execute(
            text("SELECT name_source, description_source FROM documents WHERE id = :id"),
            {"id": document["id"]},
        ).one()
    assert tuple(sources) == ("person", "person")  # the AI never replaces them (topic 1)
    assert _actions(committing_db, document["id"])[-2:] == [
        "document.renamed",
        "document.description_changed",
    ]
    moved = owner.patch(
        f"{DOCUMENTS}/{document['id']}",
        json={"require_email_code": False},
        headers=csrf_headers(owner),
    )
    assert moved.status_code == 422  # a send's setting now (Phase 7 §4)
    too_long = owner.patch(
        f"{DOCUMENTS}/{document['id']}", json={"name": "x" * 121}, headers=csrf_headers(owner)
    )
    assert too_long.status_code == 422


def test_archived_documents_refuse_changes_and_restore_onto_a_free_name(
    owner: TestClient,
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes(1), name="NDA").json()
    archived = owner.post(f"{DOCUMENTS}/{document['id']}/archive", headers=csrf_headers(owner))
    assert archived.json()["archived_at"] is not None
    assert (
        owner.post(f"{DOCUMENTS}/{document['id']}/archive", headers=csrf_headers(owner)).status_code
        == 200
    )

    assert add_version(owner, document["id"], pdf_bytes(2), department["id"]).json()["code"] == (
        "document-archived"
    )
    new_document(owner, department["id"], pdf_bytes(3), name="NDA")  # the name is free again
    blocked = owner.post(f"{DOCUMENTS}/{document['id']}/restore", headers=csrf_headers(owner))
    assert blocked.json()["code"] == "document-name-taken"
    listed = owner.get(f"{DEPARTMENTS}/{department['id']}/documents", params={"status": "archived"})
    assert [d["id"] for d in listed.json()] == [document["id"]]


def test_viewers_read_but_do_not_change_and_other_companies_see_nothing(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
    make_workspace: Callable[..., Account],
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        seen = theirs.get(f"{DOCUMENTS}/{document['id']}")
        assert (seen.status_code, seen.json()["access"]) == (200, "read")
        assert (
            theirs.patch(
                f"{DOCUMENTS}/{document['id']}", json={"name": "X"}, headers=csrf_headers(theirs)
            ).status_code
            == 403
        )
    stranger = make_workspace(workspace_name="Baker & Co")
    with make_client() as theirs:
        log_in(theirs, stranger.email)
        assert theirs.get(f"{DOCUMENTS}/{document['id']}").status_code == 404
        assert theirs.get(f"{DEPARTMENTS}/{department['id']}/documents").status_code == 404


def test_creating_replays_with_its_key(owner: TestClient) -> None:
    department = create_department(owner)
    upload_id = upload(owner, department["id"], pdf_bytes()).json()["id"]
    headers = {**csrf_headers(owner), **idempotency_key()}
    body = {"name": "Letter", "upload_id": upload_id}

    first = owner.post(f"{DEPARTMENTS}/{department['id']}/documents", json=body, headers=headers)
    second = owner.post(f"{DEPARTMENTS}/{department['id']}/documents", json=body, headers=headers)

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] == second.json()["id"]
