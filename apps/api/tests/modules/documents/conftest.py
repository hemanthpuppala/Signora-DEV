"""Document tests reuse the identity fixtures, with blobs in a temporary directory."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.blobstore import LocalBlobStore
from signora.kernel.config import DatabaseSettings, Settings, load_settings
from signora.kernel.db import Database
from signora.kernel.jobs import JobContext
from signora.modules.documents import processing
from tests.modules.identity_access.conftest import (  # noqa: F401 - fixtures by name
    Account,
    add_member,
    client,
    csrf_headers,
    idempotency_key,
    log_in,
    make_client,
    make_workspace,
)

__all__ = ["Account", "csrf_headers", "idempotency_key", "log_in"]

DEPARTMENTS = "/api/v1/departments"


@pytest.fixture
def settings(test_db_settings: DatabaseSettings, tmp_path: Path) -> Settings:
    base = load_settings()
    return base.model_copy(
        update={
            "db": test_db_settings,
            "blob_store": base.blob_store.model_copy(update={"dir": tmp_path / "blobs"}),
        }
    )


@pytest.fixture
def company(make_workspace: Callable[..., Account]) -> Account:  # noqa: F811 - fixture argument
    return make_workspace()


@pytest.fixture
def owner(client: TestClient, company: Account) -> TestClient:  # noqa: F811 - fixture argument
    log_in(client, company.email)
    return client


def create_department(api: TestClient, name: str = "Finance") -> Any:
    response = api.post(
        DEPARTMENTS, json={"name": name}, headers={**csrf_headers(api), **idempotency_key()}
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(api: TestClient, department_id: str, data: bytes, filename: str = "Letter.pdf") -> Any:
    return api.post(
        f"{DEPARTMENTS}/{department_id}/uploads",
        params={"filename": filename},
        content=data,
        headers={**csrf_headers(api), "Content-Type": "application/octet-stream"},
    )


def new_document(
    api: TestClient,
    department_id: str,
    data: bytes,
    name: str = "Engagement letter",
    **extra: Any,
) -> Any:
    """Upload then create; returns the create response."""
    uploaded = upload(api, department_id, data)
    assert uploaded.status_code == 201, uploaded.text
    return api.post(
        f"{DEPARTMENTS}/{department_id}/documents",
        json={"name": name, "upload_id": uploaded.json()["id"], **extra},
        headers={**csrf_headers(api), **idempotency_key()},
    )


def add_version(api: TestClient, document_id: str, data: bytes, department_id: str) -> Any:
    uploaded = upload(api, department_id, data)
    assert uploaded.status_code == 201, uploaded.text
    return api.post(
        f"/api/v1/documents/{document_id}/versions",
        json={"upload_id": uploaded.json()["id"]},
        headers={**csrf_headers(api), **idempotency_key()},
    )


@pytest.fixture
def run(committing_db: Database, settings: Settings) -> Callable[..., None]:
    """Run the processing job for a version, as the worker would."""

    def go(version_id: str, *, attempt: int = 1, gotenberg_url: str | None = None) -> None:
        with committing_db.unit_of_work() as uow:
            job_id = uow.session.execute(
                text(
                    "INSERT INTO jobs (kind, status, attempts) "
                    "VALUES ('document.process', 'running', :a) RETURNING id"
                ),
                {"a": attempt},
            ).scalar_one()
        processing.process_version(
            JobContext(
                job_id, processing.PROCESS, {"version_id": version_id}, {}, attempt, committing_db
            ),
            store=LocalBlobStore(settings.blob_store.dir),
            gotenberg_url=gotenberg_url or settings.gotenberg.base_url,
            max_pages=settings.documents.max_pages,
        )

    return go
