"""Who can see and do what inside a department (Phase 3 LLD topic 2)."""

from __future__ import annotations

import contextlib
import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from signora.modules.departments import access as access_module
from signora.modules.departments import load_access
from signora.modules.departments import service as service_module
from signora.modules.identity_access import Permission
from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.domain.permissions import parse_permissions
from tests.modules.identity_access.conftest import (
    Account,
    csrf_headers,
    idempotency_key,
    log_in,
)

URL = "/api/v1/departments"


def create(client: TestClient, name: str) -> Any:
    return client.post(
        URL, json={"name": name}, headers={**csrf_headers(client), **idempotency_key()}
    ).json()


def put_grants(client: TestClient, department_id: str, user_ids: list[Any]) -> Any:
    return client.put(
        f"{URL}/{department_id}/grants",
        json={"user_ids": [str(u) for u in user_ids]},
        headers=csrf_headers(client),
    )


@pytest.fixture
def company(make_workspace: Callable[..., Account]) -> Account:
    return make_workspace()


@pytest.fixture
def owner(client: TestClient, company: Account) -> TestClient:
    log_in(client, company.email)
    return client


def actor_for(db: Database, account: Account) -> Actor:
    """The member's actor as a request would see it (role permissions from the database)."""
    with db.unit_of_work() as uow:
        row = uow.session.execute(
            text(
                "SELECT r.key, r.name, r.permissions FROM users u JOIN roles r ON r.id = u.role_id "
                "WHERE u.id = :u"
            ),
            {"u": account.user_id},
        ).one()
    return Actor(
        user_id=account.user_id,
        email=account.email,
        name="x",
        workspace_id=account.workspace_id,
        workspace_name="x",
        role_id=uuid.uuid4(),
        role_key=row.key,
        role_name=row.name,
        role_description="",
        permissions=parse_permissions(row.permissions)[0],
        is_creator=False,
        session_digest=b"",
    )


def test_a_grant_gives_edit_access_in_that_department_only(
    owner: TestClient,
    committing_db: Database,
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    finance, hr = create(owner, "Finance"), create(owner, "HR")
    viewer = add_member(company, role="read")

    assert put_grants(owner, finance["id"], [viewer.user_id]).status_code == 200

    with committing_db.unit_of_work() as uow:
        rights = load_access(uow.session, actor_for(committing_db, viewer))
    finance_id, hr_id = uuid.UUID(finance["id"]), uuid.UUID(hr["id"])
    assert rights.can(Permission.FILES_SEND, finance_id)
    assert rights.can(Permission.FILES_VIEW_SENDS, finance_id)
    assert not rights.can(Permission.FILES_SEND, hr_id)
    assert not rights.can(Permission.DEPARTMENTS_MANAGE, finance_id)  # grants never give this


def test_each_department_reports_the_callers_access(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    finance, hr = create(owner, "Finance"), create(owner, "HR")
    viewer = add_member(company, role="read")
    editor = add_member(company, role="read_write")
    put_grants(owner, finance["id"], [viewer.user_id])

    def access(email: str) -> dict[str, str]:
        with make_client() as client:
            log_in(client, email)
            return {d["name"]: d["access"] for d in client.get(URL).json()}

    assert access(viewer.email) == {"Finance": "edit", "HR": "read"}
    assert access(editor.email) == {"Finance": "edit", "HR": "edit"}  # the role covers all
    assert {d["name"]: d["access"] for d in owner.get(URL).json()} == {
        "Finance": "edit",
        "HR": "edit",
    }
    assert hr["access"] == "edit"


def test_replacing_the_list_adds_and_removes_exactly_the_difference(
    owner: TestClient, committing_db: Database, company: Account, add_member: Callable[..., Account]
) -> None:
    department = create(owner, "Intake")
    a, b, c = (add_member(company, role="read") for _ in range(3))

    put_grants(owner, department["id"], [a.user_id, b.user_id])
    response = put_grants(owner, department["id"], [b.user_id, c.user_id, c.user_id])

    assert {g["user"]["id"] for g in response.json()} == {str(b.user_id), str(c.user_id)}
    assert response.json()[0]["granted_by"]["id"] == str(company.user_id)
    with committing_db.unit_of_work() as uow:
        actions = uow.session.execute(
            text(
                "SELECT action, data->>'user_id' AS who FROM audit_events "
                "WHERE workspace_id = :w AND action LIKE 'department.access_%' ORDER BY seq"
            ),
            {"w": company.workspace_id},
        ).all()
    assert [(row.action, row.who) for row in actions] == [
        ("department.access_granted", str(a.user_id)),
        ("department.access_granted", str(b.user_id)),
        ("department.access_granted", str(c.user_id)),
        ("department.access_revoked", str(a.user_id)),
    ]
    same = put_grants(owner, department["id"], [b.user_id, c.user_id])
    assert same.status_code == 200  # repeat-safe: nothing more is audited


def test_only_people_managers_read_or_change_grants(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    department = create(owner, "Finance")
    editor = add_member(company, role="read_write")
    with make_client() as client:
        log_in(client, editor.email)
        assert client.get(f"{URL}/{department['id']}/grants").status_code == 403
        assert put_grants(client, department["id"], [editor.user_id]).status_code == 403


def test_inactive_unknown_and_other_company_people_are_refused(
    owner: TestClient,
    committing_db: Database,
    company: Account,
    add_member: Callable[..., Account],
    make_workspace: Callable[..., Account],
) -> None:
    department = create(owner, "Finance")
    removed = add_member(company)
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :u"), {"u": removed.user_id}
        )
    stranger = make_workspace(workspace_name="Baker & Co")

    response = put_grants(
        owner, department["id"], [removed.user_id, uuid.uuid4(), stranger.user_id]
    )

    assert response.status_code == 422
    assert [e["field"] for e in response.json()["errors"]] == [
        "user_ids[0]",
        "user_ids[1]",
        "user_ids[2]",
    ]


def test_grants_on_an_archived_or_foreign_department_are_refused(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
    make_workspace: Callable[..., Account],
) -> None:
    department = create(owner, "Old")
    owner.post(f"{URL}/{department['id']}/archive", headers=csrf_headers(owner))
    member = add_member(company)
    assert put_grants(owner, department["id"], [member.user_id]).json()["code"] == (
        "department-archived"
    )

    other = make_workspace(workspace_name="Baker & Co")
    with make_client() as theirs:
        log_in(theirs, other.email)
        foreign = create(theirs, "Theirs")
    assert owner.get(f"{URL}/{foreign['id']}/grants").status_code == 404
    assert put_grants(owner, foreign["id"], []).status_code == 404


def test_candidates_leave_out_people_who_already_edit_everywhere(
    owner: TestClient, company: Account, add_member: Callable[..., Account]
) -> None:
    department = create(owner, "Finance")
    viewer = add_member(company, role="read")
    editor = add_member(company, role="read_write")

    candidates = owner.get(f"{URL}/{department['id']}/grants/candidates").json()

    assert [c["id"] for c in candidates] == [str(viewer.user_id)]  # not the creator, not editors
    refused = put_grants(owner, department["id"], [company.user_id, editor.user_id])
    assert refused.status_code == 422
    assert {e["message"] for e in refused.json()["errors"]} == {
        "Already has edit access through their role"
    }


def test_two_first_grants_at_once_both_succeed(
    owner: TestClient,
    committing_db: Database,
    company: Account,
    add_member: Callable[..., Account],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no grants yet there are no rows to lock; the department row serialises the two."""
    department = create(owner, "Intake")
    carol = add_member(company, role="read")
    actor = actor_for(committing_db, company)
    barrier = threading.Barrier(2)
    real_lock = service_module.lock_active_department

    def lock_then_wait(session: Any, workspace_id: uuid.UUID, department_id: uuid.UUID) -> None:
        real_lock(session, workspace_id, department_id)
        # Without a real lock both requests meet here and read the same empty list. With it, the
        # second waits inside the lock, so the first gives up waiting and commits first.
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=2)

    monkeypatch.setattr(access_module, "lock_active_department", lock_then_wait)
    errors: list[BaseException] = []

    def grant() -> None:
        try:
            with committing_db.unit_of_work() as uow:
                access_module.set_grants(
                    uow,
                    actor=actor,
                    department_id=uuid.UUID(department["id"]),
                    user_ids=[carol.user_id],
                )
        except BaseException as error:  # collected for the assertion
            errors.append(error)

    threads = [threading.Thread(target=grant) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []  # never a primary-key violation
    with committing_db.unit_of_work() as uow:
        granted = uow.session.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE workspace_id = :w AND action = 'department.access_granted'"
            ),
            {"w": company.workspace_id},
        ).scalar_one()
    assert granted == 1  # the second request found Carol already granted
