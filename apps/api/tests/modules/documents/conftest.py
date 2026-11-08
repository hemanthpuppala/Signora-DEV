"""Document tests reuse the identity fixtures, with blobs in a temporary directory."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from signora.kernel.config import DatabaseSettings, Settings, load_settings
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
