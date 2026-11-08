"""Uploads: the first step (Phase 4 LLD topic 2)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.config import Settings
from signora.kernel.db import Database
from signora.kernel.jobs import JobContext
from signora.modules.documents import uploads as uploads_module
from tests.modules.documents.conftest import (
    DEPARTMENTS,
    Account,
    create_department,
    csrf_headers,
    log_in,
    upload,
)
from tests.support.files import (
    docm_bytes,
    docx_bytes,
    encrypted_word_bytes,
    pdf_bytes,
    zip_bytes,
)


def test_a_pdf_is_stored_by_its_hash_and_recorded(
    owner: TestClient, settings: Settings, committing_db: Database
) -> None:
    department = create_department(owner)
    data = pdf_bytes(2)

    response = upload(owner, department["id"], data, filename="Engagement letter v3.pdf")

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["kind"], body["bytes"], body["filename"]) == (
        "pdf",
        len(data),
        "Engagement letter v3.pdf",
    )
    assert body["suggested_name"] == "Engagement letter v3"
    with committing_db.unit_of_work() as uow:
        row = uow.session.execute(
            text("SELECT sha256, workspace_id, used_at FROM uploads WHERE id = :id"),
            {"id": body["id"]},
        ).one()
    assert row.used_at is None
    h = row.sha256
    key = f"workspaces/{row.workspace_id}/blobs/sha256/{h[:2]}/{h[2:4]}/{h}"
    assert (settings.blob_store.dir / key).read_bytes() == data


def test_a_word_file_is_recognised_from_its_contents(owner: TestClient) -> None:
    department = create_department(owner)
    response = upload(owner, department["id"], docx_bytes(), filename="letter.bin")
    assert response.status_code == 201, response.text
    assert response.json()["kind"] == "docx"


@pytest.mark.parametrize(
    "data",
    [
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        b"just some text",
        zip_bytes({"readme.txt": b"hello"}),
        docm_bytes(),
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600,  # an old .doc
        b"",
    ],
    ids=["png", "text", "zip", "docm", "doc", "empty"],
)
def test_other_files_are_refused_whatever_their_name(owner: TestClient, data: bytes) -> None:
    department = create_department(owner)
    response = upload(owner, department["id"], data, filename="contract.pdf")
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported-file"
    assert response.json()["title"] == "Upload a PDF or Word (.docx) file"


def test_a_password_protected_word_file_asks_to_remove_the_password(owner: TestClient) -> None:
    department = create_department(owner)
    response = upload(owner, department["id"], encrypted_word_bytes(), filename="locked.docx")
    assert response.status_code == 422
    assert response.json()["title"] == "Remove the password in Word and upload it again"


def test_a_file_over_the_limit_is_refused(
    make_client: Callable[..., TestClient], settings: Settings, company: Account
) -> None:
    small = settings.model_copy(
        update={"documents": settings.documents.model_copy(update={"max_bytes": 2048})}
    )
    with make_client(small) as client:
        log_in(client, company.email)
        department = create_department(client)
        response = upload(client, department["id"], b"%PDF-" + b"x" * 4096)
    assert response.status_code == 413
    assert response.json()["code"] == "payload-too-large"


def test_the_file_name_keeps_only_its_base_name(owner: TestClient) -> None:
    department = create_department(owner)
    response = upload(owner, department["id"], pdf_bytes(), filename="C:\\fakepath\\NDA\x07.pdf")
    assert response.json()["filename"] == "NDA.pdf"
    assert response.json()["suggested_name"] == "NDA"


def test_uploading_needs_edit_access_in_an_active_department_of_the_company(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
    make_workspace: Callable[..., Account],
) -> None:
    department = create_department(owner)
    archived = create_department(owner, "Old")
    owner.post(f"{DEPARTMENTS}/{archived['id']}/archive", headers=csrf_headers(owner))
    viewer = add_member(company, role="read")
    with make_client() as client:
        log_in(client, viewer.email)
        assert upload(client, department["id"], pdf_bytes()).status_code == 403
    assert upload(owner, archived["id"], pdf_bytes()).json()["code"] == "department-archived"
    assert upload(owner, str(uuid.uuid4()), pdf_bytes()).status_code == 404
    other = make_workspace(workspace_name="Baker & Co")
    with make_client() as theirs:
        log_in(theirs, other.email)
        foreign = create_department(theirs)
    assert upload(owner, foreign["id"], pdf_bytes()).status_code == 404


def test_uploads_are_limited_per_person_per_hour(
    make_client: Callable[..., TestClient], settings: Settings, company: Account
) -> None:
    limited = settings.model_copy(
        update={"documents": settings.documents.model_copy(update={"uploads_per_hour": 2})}
    )
    with make_client(limited) as client:
        log_in(client, company.email)
        department = create_department(client)
        statuses = [upload(client, department["id"], pdf_bytes()).status_code for _ in range(3)]
    assert statuses == [201, 201, 429]


def test_the_sweep_forgets_uploads_after_a_day(
    owner: TestClient, committing_db: Database, tmp_path: Path
) -> None:
    department = create_department(owner)
    old = upload(owner, department["id"], pdf_bytes()).json()["id"]
    fresh = upload(owner, department["id"], pdf_bytes()).json()["id"]
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE uploads SET expires_at = now() - interval '1 minute' WHERE id = :id"),
            {"id": old},
        )
        job_id = uow.session.execute(
            text(
                "INSERT INTO jobs (kind, status, attempts) VALUES ('sweep.uploads', 'running', 1) "
                "RETURNING id"
            )
        ).scalar_one()

    uploads_module.sweep(
        JobContext(job_id, "sweep.uploads", {}, {}, attempt=1, database=committing_db)
    )

    with committing_db.unit_of_work() as uow:
        left = {
            str(i)
            for i in uow.session.execute(
                text("SELECT id FROM uploads WHERE id IN (:a, :b)"), {"a": old, "b": fresh}
            ).scalars()
        }
    assert left == {fresh}
