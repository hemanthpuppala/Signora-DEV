"""Departments: what they are and who manages them (Phase 3 LLD topic 1)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.identity_access.conftest import (
    Account,
    csrf_headers,
    idempotency_key,
    log_in,
)

URL = "/api/v1/departments"


def create(client: TestClient, name: str, description: str = "") -> Any:
    return client.post(
        URL,
        json={"name": name, "description": description},
        headers={**csrf_headers(client), **idempotency_key()},
    )


def post(client: TestClient, path: str) -> Any:
    return client.post(path, headers=csrf_headers(client))


def patch(client: TestClient, path: str, body: dict[str, Any]) -> Any:
    return client.patch(path, json=body, headers=csrf_headers(client))


@pytest.fixture
def company(make_workspace: Callable[..., Account]) -> Account:
    return make_workspace(workspace_name="Hale & Ward LLP")


@pytest.fixture
def owner(client: TestClient, company: Account) -> TestClient:
    log_in(client, company.email)
    return client


def audit_actions(db: Database, company: Account) -> list[str]:
    with db.unit_of_work() as uow:
        return list(
            uow.session.execute(
                text(
                    "SELECT action FROM audit_events WHERE workspace_id = :w "
                    "AND action LIKE 'department.%' ORDER BY seq"
                ),
                {"w": company.workspace_id},
            ).scalars()
        )


def test_create_normalises_the_name_and_records_who(
    owner: TestClient, committing_db: Database, company: Account
) -> None:
    response = create(owner, "  Client   Intake ", "  New clients  ")

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["description"], body["status"]) == (
        "Client Intake",
        "New clients",
        "active",
    )
    assert body["created_by"] == {"id": str(company.user_id), "name": "Rosa Hale"}
    assert body["counts"] == {"sent": 0, "signed": 0, "pending": 0, "to_approve": 0}
    assert audit_actions(committing_db, company) == ["department.created"]


@pytest.mark.parametrize(
    ("name", "description", "field"),
    [("   ", "", "name"), ("x" * 81, "", "name"), ("Finance", "y" * 501, "description")],
)
def test_lengths_are_checked_after_normalising(
    owner: TestClient, name: str, description: str, field: str
) -> None:
    response = create(owner, name, description)
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == field


def test_names_are_unique_per_company_ignoring_case_among_active(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    make_workspace: Callable[..., Account],
) -> None:
    first = create(owner, "Finance").json()
    taken = create(owner, "FINANCE")
    assert taken.status_code == 409
    assert taken.json()["code"] == "department-name-taken"

    post(owner, f"{URL}/{first['id']}/archive")
    assert create(owner, "finance").status_code == 201  # an archived department frees its name

    other = make_workspace(workspace_name="Baker & Co")
    with make_client() as theirs:
        log_in(theirs, other.email)
        assert create(theirs, "Finance").status_code == 201  # another company: no clash


def test_two_creations_with_one_name_at_once_give_201_and_409(owner: TestClient) -> None:
    results: list[int] = []
    barrier = threading.Barrier(2)

    def send() -> None:
        barrier.wait()
        results.append(create(owner, "Race Dept").status_code)

    threads = [threading.Thread(target=send) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [201, 409]


def test_list_is_sorted_and_split_by_status(owner: TestClient) -> None:
    for name in ("intake", "Finance", "HR"):
        create(owner, name)
    archived = create(owner, "Old Matters").json()
    post(owner, f"{URL}/{archived['id']}/archive")

    active = [d["name"] for d in owner.get(URL).json()]
    old = [d["name"] for d in owner.get(URL, params={"status": "archived"}).json()]

    assert active == ["Finance", "HR", "intake"]
    assert old == ["Old Matters"]


def test_update_records_old_and_new_and_refuses_an_archived_department(
    owner: TestClient, committing_db: Database, company: Account
) -> None:
    department = create(owner, "Finance", "Money").json()
    url = f"{URL}/{department['id']}"

    renamed = patch(owner, url, {"name": "Finance & Tax"})
    assert renamed.json()["name"] == "Finance & Tax"
    assert patch(owner, url, {"name": "Finance & Tax"}).status_code == 200  # no change: no entry

    post(owner, f"{url}/archive")
    refused = patch(owner, url, {"description": "x"})
    assert refused.json()["code"] == "department-archived"

    with committing_db.unit_of_work() as uow:
        data = uow.session.execute(
            text(
                "SELECT data FROM audit_events WHERE workspace_id = :w "
                "AND action = 'department.updated'"
            ),
            {"w": company.workspace_id},
        ).scalar_one()
    assert data == {"changes": {"name": {"old": "Finance", "new": "Finance & Tax"}}}


def test_archive_and_restore_are_repeat_safe(
    owner: TestClient, committing_db: Database, company: Account
) -> None:
    department = create(owner, "HR").json()
    url = f"{URL}/{department['id']}"

    first, again = post(owner, f"{url}/archive"), post(owner, f"{url}/archive")
    assert first.json()["status"] == again.json()["status"] == "archived"
    assert first.json()["archived_at"] == again.json()["archived_at"]
    restored, again = post(owner, f"{url}/restore"), post(owner, f"{url}/restore")
    assert restored.json()["status"] == again.json()["status"] == "active"

    actions = audit_actions(committing_db, company)
    assert actions.count("department.archived") == 1
    assert actions.count("department.restored") == 1


def test_restoring_onto_a_taken_name_is_refused(owner: TestClient) -> None:
    old = create(owner, "Payroll").json()
    post(owner, f"{URL}/{old['id']}/archive")
    create(owner, "payroll")

    refused = post(owner, f"{URL}/{old['id']}/restore")

    assert refused.status_code == 409
    assert refused.json()["code"] == "department-name-taken"


def test_viewers_read_but_cannot_change(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    department = create(owner, "Finance").json()
    url = f"{URL}/{department['id']}"
    editor = add_member(company, role="read_write")
    viewer = add_member(company, role="read")

    with make_client() as client:
        log_in(client, viewer.email)
        assert client.get(URL).status_code == 200
        assert client.get(url).status_code == 200
        for response in (
            create(client, "Mine"),
            patch(client, url, {"name": "Mine"}),
            post(client, f"{url}/archive"),
            post(client, f"{url}/restore"),
        ):
            assert response.status_code == 403

    with make_client() as client:
        log_in(client, editor.email)
        assert create(client, "Editors Can").status_code == 201
        assert patch(client, url, {"description": "ok"}).status_code == 200


def test_another_companys_department_is_not_found(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    make_workspace: Callable[..., Account],
) -> None:
    other = make_workspace(workspace_name="Baker & Co")
    with make_client() as theirs:
        log_in(theirs, other.email)
        theirs_id = create(theirs, "Secret").json()["id"]

    url = f"{URL}/{theirs_id}"
    for response in (
        owner.get(url),
        patch(owner, url, {"name": "Mine"}),
        post(owner, f"{url}/archive"),
        post(owner, f"{url}/restore"),
    ):
        assert response.status_code == 404
    assert "Secret" not in [d["name"] for d in owner.get(URL).json()]


def test_creation_replays_with_the_same_key(owner: TestClient) -> None:
    headers = {**csrf_headers(owner), **idempotency_key()}
    first = owner.post(URL, json={"name": "Intake"}, headers=headers)
    again = owner.post(URL, json={"name": "Intake"}, headers=headers)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
