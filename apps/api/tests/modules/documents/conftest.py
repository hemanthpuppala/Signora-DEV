"""Document tests reuse the identity fixtures, with blobs in a temporary directory."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.blobstore import LocalBlobStore
from signora.kernel.config import DatabaseSettings, Settings, load_settings
from signora.kernel.db import Database
from signora.kernel.jobs import JobContext, JobRegistry
from signora.kernel.jobs.core import ClaimedJob, mark_failed
from signora.modules.documents import jobs, lifecycle, processing
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
from tests.support.actors import actor_for

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
    """Run the processing job for a version, as the worker would, failures included."""
    registry = JobRegistry()
    jobs.register(registry)
    kind = registry.get(processing.PROCESS)

    def go(version_id: str, *, attempt: int = 1, gotenberg_url: str | None = None) -> None:
        payload = {"version_id": version_id}
        with committing_db.unit_of_work() as uow:
            job_id = uow.session.execute(
                text(
                    "INSERT INTO jobs (kind, status, attempts, payload) "
                    "VALUES ('document.process', 'running', :a, CAST(:p AS jsonb)) RETURNING id"
                ),
                {"a": attempt, "p": json.dumps(payload)},
            ).scalar_one()
        try:
            processing.process_version(
                JobContext(job_id, processing.PROCESS, payload, {}, attempt, committing_db),
                store=LocalBlobStore(settings.blob_store.dir),
                gotenberg_url=gotenberg_url or settings.gotenberg.base_url,
                max_pages=settings.documents.max_pages,
            )
        except Exception as error:
            with committing_db.unit_of_work() as uow:
                job = ClaimedJob(job_id, processing.PROCESS, payload, {}, attempt)
                mark_failed(uow.session, job, kind, error)
            raise

    return go


@pytest.fixture
def ready(run: Callable[..., None], committing_db: Database) -> Callable[..., None]:
    """Process a version, then finish its detection with no fields, as the detection module does
    through ``documents.lifecycle`` (Phase 5 §1.2): for tests of what happens once it is ready."""

    def go(version_id: str, **options: Any) -> None:
        run(version_id, **options)
        with committing_db.unit_of_work() as uow:
            version = lifecycle.version_for_detection(uow.session, uuid.UUID(version_id))
            if version is not None and version.status == "detecting":
                lifecycle.finish_detection(uow, version, field_count=0, name=None, description=None)

    return go


@pytest.fixture
def approved(
    ready: Callable[..., None], committing_db: Database, company: Account
) -> Callable[..., None]:
    """Make a version ready, then approve it as the owner (Phase 6 §1.3): for tests of what
    happens once it is approved (current version, frozen fields)."""

    def go(version_id: str, **options: Any) -> None:
        ready(version_id, **options)
        with committing_db.unit_of_work() as uow:
            document_id = uow.session.execute(
                text("SELECT document_id FROM document_versions WHERE id = :v"), {"v": version_id}
            ).scalar_one()
            lifecycle.approve_version(
                uow,
                actor=actor_for(committing_db, company),
                document_id=document_id,
                version_id=uuid.UUID(version_id),
            )

    return go
