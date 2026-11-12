"""Who may countersign for a department (Phase 3 LLD topic 4)."""

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
from signora.modules.departments import countersigners as countersigners_module
from signora.modules.departments import service as service_module
from signora.modules.identity_access.access import Actor
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


def put_signers(client: TestClient, department_id: str, user_ids: list[Any]) -> Any:
    return client.put(
        f"{URL}/{department_id}/countersigners",
        json={"user_ids": [str(u) for u in user_ids]},
        headers=csrf_headers(client),
    )


def signer_ids(client: TestClient, department_id: str) -> list[str]:
    return [s["id"] for s in client.get(f"{URL}/{department_id}").json()["countersigners"]]


@pytest.fixture
def company(make_workspace: Callable[..., Account]) -> Account:
    return make_workspace()


@pytest.fixture
def owner(client: TestClient, company: Account) -> TestClient:
    log_in(client, company.email)
    return client


def test_the_list_keeps_its_order_and_can_be_replaced(
    owner: TestClient, company: Account, add_member: Callable[..., Account]
) -> None:
    department = create(owner, "Finance")
    a, b, c = (add_member(company, role="read") for _ in range(3))  # Viewers can be listed

    first = put_signers(owner, department["id"], [b.user_id, a.user_id])
    assert [s["id"] for s in first.json()] == [str(b.user_id), str(a.user_id)]
    assert set(first.json()[0]) == {"id", "name", "email"}

    put_signers(owner, department["id"], [c.user_id, b.user_id])
    assert signer_ids(owner, department["id"]) == [str(c.user_id), str(b.user_id)]
    assert put_signers(owner, department["id"], []).json() == []  # no lower or upper limit


def test_changes_are_audited_by_kind(
    owner: TestClient, committing_db: Database, company: Account, add_member: Callable[..., Account]
) -> None:
    department = create(owner, "Audit")
    a, b = add_member(company), add_member(company)

    put_signers(owner, department["id"], [a.user_id, b.user_id])
    put_signers(owner, department["id"], [b.user_id, a.user_id])  # reorder only
    put_signers(owner, department["id"], [b.user_id, a.user_id])  # no change: nothing audited
    put_signers(owner, department["id"], [b.user_id])

    with committing_db.unit_of_work() as uow:
        actions = (
            uow.session.execute(
                text(
                    "SELECT action FROM audit_events WHERE workspace_id = :w "
                    "AND action LIKE 'department.countersigner%' ORDER BY seq"
                ),
                {"w": company.workspace_id},
            )
            .scalars()
            .all()
        )
    assert actions == [
        "department.countersigner_added",
        "department.countersigner_added",
        "department.countersigners_reordered",
        "department.countersigner_removed",
    ]


def test_duplicates_inactive_and_foreign_people_are_refused(
    owner: TestClient,
    committing_db: Database,
    company: Account,
    add_member: Callable[..., Account],
    make_workspace: Callable[..., Account],
) -> None:
    department = create(owner, "Checks")
    member, removed = add_member(company), add_member(company)
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :u"), {"u": removed.user_id}
        )
    stranger = make_workspace(workspace_name="Baker & Co")

    response = put_signers(
        owner,
        department["id"],
        [member.user_id, member.user_id, removed.user_id, stranger.user_id, uuid.uuid4()],
    )

    assert response.status_code == 422
    assert [e["field"] for e in response.json()["errors"]] == [
        "user_ids[1]",
        "user_ids[2]",
        "user_ids[3]",
        "user_ids[4]",
    ]


def test_only_owners_and_editors_manage_the_list(
    owner: TestClient,
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    department = create(owner, "Finance")
    viewer = add_member(company, role="read")
    owner.put(
        f"{URL}/{department['id']}/grants",
        json={"user_ids": [str(viewer.user_id)]},
        headers=csrf_headers(owner),
    )
    editor = add_member(company, role="read_write")

    with make_client() as client:
        log_in(client, viewer.email)  # has a grant here, which does not include managing
        assert put_signers(client, department["id"], [viewer.user_id]).status_code == 403
    with make_client() as client:
        log_in(client, editor.email)
        assert put_signers(client, department["id"], [editor.user_id]).status_code == 200


def test_removing_a_member_takes_them_off_every_list(
    owner: TestClient,
    committing_db: Database,
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    finance, hr = create(owner, "Finance"), create(owner, "HR")
    leaving, staying = add_member(company), add_member(company)
    put_signers(owner, finance["id"], [leaving.user_id, staying.user_id])
    put_signers(owner, hr["id"], [leaving.user_id])

    removed = owner.delete(f"/api/v1/members/{leaving.user_id}", headers=csrf_headers(owner))

    assert removed.status_code == 204
    assert signer_ids(owner, finance["id"]) == [str(staying.user_id)]
    assert signer_ids(owner, hr["id"]) == []  # the department now reports no countersigner
    with committing_db.unit_of_work() as uow:  # the rows are gone, not merely hidden
        rows = uow.session.execute(
            text("SELECT count(*) FROM department_countersigners WHERE user_id = :u"),
            {"u": leaving.user_id},
        ).scalar_one()
    assert rows == 0


def test_an_archived_department_refuses_changes(
    owner: TestClient, company: Account, add_member: Callable[..., Account]
) -> None:
    department = create(owner, "Old")
    owner.post(f"{URL}/{department['id']}/archive", headers=csrf_headers(owner))
    response = put_signers(owner, department["id"], [add_member(company).user_id])
    assert response.json()["code"] == "department-archived"


def test_two_first_countersigners_at_once_both_succeed(
    owner: TestClient,
    committing_db: Database,
    company: Account,
    add_member: Callable[..., Account],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With an empty list there are no rows to lock; the department row serialises the two."""
    department = create(owner, "Intake")
    ana = add_member(company)
    actor = Actor(
        user_id=company.user_id,
        email=company.email,
        name="x",
        workspace_id=company.workspace_id,
        workspace_name="x",
        workspace_website=None,
        workspace_logo=None,
        role_id=uuid.uuid4(),  # the service reads only the company, user and email
        role_key="x",
        role_name="x",
        role_description="",
        permissions=frozenset(),
        is_creator=True,
        session_digest=b"",
    )
    barrier = threading.Barrier(2)
    real_lock = service_module.lock_active_department

    def lock_then_wait(session: Any, workspace_id: uuid.UUID, department_id: uuid.UUID) -> None:
        real_lock(session, workspace_id, department_id)
        # Without a real lock both requests meet here and read the same empty list. With it, the
        # second waits inside the lock, so the first gives up waiting and commits first.
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=2)

    monkeypatch.setattr(countersigners_module, "lock_active_department", lock_then_wait)
    errors: list[BaseException] = []

    def add_first() -> None:
        try:
            with committing_db.unit_of_work() as uow:
                countersigners_module.set_countersigners(
                    uow,
                    actor=actor,
                    department_id=uuid.UUID(department["id"]),
                    user_ids=[ana.user_id],
                )
        except BaseException as error:  # collected for the assertion
            errors.append(error)

    threads = [threading.Thread(target=add_first) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []  # never a duplicate position or person
    assert signer_ids(owner, department["id"]) == [str(ana.user_id)]
