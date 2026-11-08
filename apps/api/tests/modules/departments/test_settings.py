"""Department settings and defaults (Phase 3 LLD topic 3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from signora.kernel.config import Settings
from signora.kernel.db import Database
from tests.modules.identity_access.conftest import (
    Account,
    csrf_headers,
    idempotency_key,
    log_in,
)

URL = "/api/v1/departments"


def create(client: TestClient, name: str, **settings: Any) -> Any:
    body: dict[str, Any] = {"name": name}
    if settings:
        body["settings"] = settings
    return client.post(URL, json=body, headers={**csrf_headers(client), **idempotency_key()})


def change(client: TestClient, department_id: str, **settings: Any) -> Any:
    return client.patch(
        f"{URL}/{department_id}", json={"settings": settings}, headers=csrf_headers(client)
    )


@pytest.fixture
def company(make_workspace: Callable[..., Account]) -> Account:
    return make_workspace()


@pytest.fixture
def owner(client: TestClient, company: Account) -> TestClient:
    log_in(client, company.email)
    return client


def test_a_new_department_starts_from_the_company_defaults(
    owner: TestClient, settings: Settings
) -> None:
    created = create(owner, "Finance").json()

    signing = settings.signing
    assert created["settings"] == {
        "reminder_interval_hours": signing.default_reminder_interval_hours,
        "max_reminders": signing.default_max_reminders,
        "expiry_days": signing.default_expiry_days,
        "notify_emails": [],
    }


def test_creation_can_override_the_defaults(owner: TestClient) -> None:
    created = create(owner, "HR", max_reminders=0, expiry_days=30).json()
    assert created["settings"]["max_reminders"] == 0
    assert created["settings"]["expiry_days"] == 30


def test_defaults_are_copied_so_later_changes_leave_departments_alone(
    make_client: Callable[..., TestClient], settings: Settings, company: Account
) -> None:
    with make_client() as before:
        log_in(before, company.email)
        department = create(before, "Intake").json()

    changed_defaults = settings.model_copy(
        update={"signing": settings.signing.model_copy(update={"default_expiry_days": 90})}
    )
    with make_client(changed_defaults) as after:
        log_in(after, company.email)
        assert after.get(f"{URL}/{department['id']}").json()["settings"]["expiry_days"] == (
            settings.signing.default_expiry_days
        )
        assert create(after, "Later").json()["settings"]["expiry_days"] == 90


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reminder_interval_hours", 0),
        ("reminder_interval_hours", 721),
        ("max_reminders", -1),
        ("max_reminders", 21),
        ("expiry_days", 0),
        ("expiry_days", 366),
    ],
)
def test_ranges_are_enforced_by_the_api(owner: TestClient, field: str, value: int) -> None:
    department = create(owner, "Ranges").json()
    response = change(owner, department["id"], **{field: value})
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == field


@pytest.mark.parametrize(
    ("field", "value"),
    [("reminder_interval_hours", 721), ("max_reminders", 21), ("expiry_days", 0)],
)
def test_ranges_are_enforced_by_the_database_too(
    db: Database, company: Account, field: str, value: int
) -> None:
    with pytest.raises(IntegrityError, match=f"{field}_range"), db.unit_of_work() as uow:
        uow.session.execute(
            text(
                f"INSERT INTO departments (workspace_id, name, created_by, {field}) "  # noqa: S608 - test fixture names
                "VALUES (:w, 'Direct', :u, :v)"
            ),
            {"w": company.workspace_id, "u": company.user_id, "v": value},
        )


def test_notify_emails_are_normalised_merged_and_capped(owner: TestClient) -> None:
    department = create(owner, "Notify").json()

    merged = change(
        owner, department["id"], notify_emails=[" Inbox@Firm.com", "inbox@firm.com", "b@firm.com"]
    )
    assert merged.json()["settings"]["notify_emails"] == ["inbox@firm.com", "b@firm.com"]

    six = [f"p{i}@firm.com" for i in range(6)]
    too_many = change(owner, department["id"], notify_emails=six)
    assert too_many.status_code == 422
    assert too_many.json()["errors"][0]["field"] == "notify_emails"

    invalid = change(owner, department["id"], notify_emails=["ok@firm.com", "not an email"])
    assert invalid.json()["errors"][0]["field"] == "notify_emails[1]"


def test_setting_changes_are_audited_with_old_and_new(
    owner: TestClient, committing_db: Database, company: Account, settings: Settings
) -> None:
    department = create(owner, "Audited").json()
    change(owner, department["id"], max_reminders=2, notify_emails=["desk@firm.com"])

    with committing_db.unit_of_work() as uow:
        data = uow.session.execute(
            text(
                "SELECT data FROM audit_events WHERE workspace_id = :w "
                "AND action = 'department.updated'"
            ),
            {"w": company.workspace_id},
        ).scalar_one()
    assert data["changes"] == {
        "max_reminders": {"old": settings.signing.default_max_reminders, "new": 2},
        "notify_emails": {"old": [], "new": ["desk@firm.com"]},
    }


def test_viewers_cannot_change_settings(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    department = create(owner, "Viewer Check").json()
    viewer = add_member(company, role="read")
    with make_client() as client:
        log_in(client, viewer.email)
        assert change(client, department["id"], max_reminders=1).status_code == 403
