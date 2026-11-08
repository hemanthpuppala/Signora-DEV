"""Fixtures for identity tests: real app, real database (committed), unique emails per test."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from signora.entrypoints.api import create_app
from signora.kernel.config import DatabaseSettings, Settings, load_settings
from signora.kernel.db import Database
from signora.kernel.health import Check
from signora.kernel.jobs import JobRegistry
from signora.modules.identity_access import accounts
from signora.modules.identity_access import jobs as identity_jobs
from signora.modules.identity_access.dependencies import CSRF_COOKIE, CSRF_HEADER
from signora.modules.identity_access.domain.passwords import hash_password
from tests.support.workers import running_worker, wait_until

PASSWORD = "correct horse battery staple"  # noqa: S105 - test value
_HASH = hash_password(PASSWORD)  # hashed once: Argon2id is deliberately slow


def unique_email(label: str = "user") -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _no_checks(_: Settings, __: Engine) -> Sequence[Check]:
    return []


@pytest.fixture
def settings(test_db_settings: DatabaseSettings) -> Settings:
    return load_settings().model_copy(update={"db": test_db_settings})


@pytest.fixture
def make_client(settings: Settings, engine: Engine) -> Callable[..., TestClient]:
    """A client for a fresh app (fresh rate limiter). HTTPS, so Secure cookies are sent back."""

    def build(app_settings: Settings | None = None, **auth_overrides: Any) -> TestClient:
        chosen = app_settings or settings
        if auth_overrides:
            chosen = chosen.model_copy(
                update={"auth": chosen.auth.model_copy(update=auth_overrides)}
            )
        app = create_app(chosen, engine=engine, checks_factory=_no_checks)
        return TestClient(app, base_url="https://testserver", raise_server_exceptions=True)

    return build


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


@dataclass(frozen=True)
class Account:
    email: str
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role_ids: dict[str, uuid.UUID]


@pytest.fixture
def make_workspace(committing_db: Database) -> Callable[..., Account]:
    def create(email: str | None = None, workspace_name: str = "Acme Law") -> Account:
        address = email or unique_email("creator")
        with committing_db.unit_of_work() as uow:
            made = accounts.create_workspace(
                uow,
                workspace_name=workspace_name,
                creator_name="Rosa Hale",
                email=address,
                password_hash=_HASH,
            )
        return Account(address, made.user_id, made.workspace_id, made.role_ids)

    return create


@pytest.fixture
def add_member(committing_db: Database) -> Callable[..., Account]:
    def add(workspace: Account, role: str = "read", email: str | None = None) -> Account:
        address = email or unique_email(role)
        with committing_db.unit_of_work() as uow:
            user_id = uow.session.execute(
                text(
                    "INSERT INTO users (workspace_id, role_id, email, name, password_hash) "
                    "VALUES (:w, :r, :e, 'Sam Iqbal', :h) RETURNING id"
                ),
                {
                    "w": workspace.workspace_id,
                    "r": workspace.role_ids[role],
                    "e": address,
                    "h": _HASH,
                },
            ).scalar_one()
        return Account(address, user_id, workspace.workspace_id, workspace.role_ids)

    return add


@pytest.fixture
def identity_worker(committing_db: Database, test_db_settings: DatabaseSettings) -> Iterator[None]:
    """A worker running the identity jobs (sign-up and reset requests); emails stay queued."""
    reg = JobRegistry()
    identity_jobs.register(reg)
    with running_worker(committing_db, test_db_settings, reg):
        yield


def latest_email(db: Database, address: str, timeout: float = 10.0) -> Any:
    """The newest email queued for ``address``, waiting for the job to queue it."""

    def find() -> Any:
        with db.unit_of_work() as uow:
            return uow.session.execute(
                text(
                    "SELECT * FROM email_messages WHERE to_address = :a "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"a": address},
            ).one_or_none()

    wait_until(lambda: find() is not None, timeout=timeout)
    return find()


def emails_to(db: Database, address: str) -> list[Any]:
    with db.unit_of_work() as uow:
        return list(
            uow.session.execute(
                text("SELECT * FROM email_messages WHERE to_address = :a ORDER BY created_at"),
                {"a": address},
            ).all()
        )


def link_token(email_row: Any, path: str) -> str:
    match = re.search(rf"{re.escape(path)}#([A-Za-z0-9_-]+)", email_row.text_body)
    assert match, email_row.text_body
    return match.group(1)


def idempotency_key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def log_in(client: TestClient, email: str, password: str = PASSWORD) -> Any:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {CSRF_HEADER: client.cookies.get(CSRF_COOKIE) or ""}
