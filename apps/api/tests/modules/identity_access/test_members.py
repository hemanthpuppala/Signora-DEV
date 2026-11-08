"""People, roles, workspace and profile (Phase 2 LLD topic 8), with tenant isolation (FR-A11)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.identity_access.conftest import Account, csrf_headers, log_in


@pytest.fixture
def workspace(make_workspace: Callable[..., Account]) -> Account:
    return make_workspace(workspace_name="Hale & Ward LLP")


@pytest.fixture
def manager(client: TestClient, workspace: Account) -> TestClient:
    log_in(client, workspace.email)
    return client


def patch(client: TestClient, url: str, body: dict[str, Any]) -> Any:
    return client.patch(url, json=body, headers=csrf_headers(client))


def delete(client: TestClient, url: str) -> Any:
    return client.delete(url, headers=csrf_headers(client))


def actions(db: Database, workspace: Account) -> list[str]:
    with db.unit_of_work() as uow:
        return list(
            uow.session.execute(
                text("SELECT action FROM audit_events WHERE workspace_id = :w ORDER BY seq"),
                {"w": workspace.workspace_id},
            ).scalars()
        )


def test_people_lists_active_members_with_roles_creator_first(
    manager: TestClient, workspace: Account, add_member: Callable[..., Account]
) -> None:
    add_member(workspace, role="read")

    members = manager.get("/api/v1/members").json()

    assert [m["is_creator"] for m in members] == [True, False]
    assert members[0]["role"]["name"] == "Editor"
    assert members[1]["role"]["name"] == "Viewer"
    assert members[1]["role"]["description"].startswith("Can see departments")
    assert members[0]["display_role"]["name"] == "Owner"  # the creator, in people's words
    assert members[1]["display_role"]["name"] == "Viewer"
    assert {"id", "name", "email", "role", "display_role", "is_creator", "joined_at"} == set(
        members[0]
    )


def test_people_and_roles_are_the_creators_by_default(
    make_client: Callable[..., TestClient],
    workspace: Account,
    add_member: Callable[..., Account],
) -> None:
    for role in ("read_write", "read"):
        member = add_member(workspace, role=role)
        with make_client() as client:
            log_in(client, member.email)
            assert client.get("/api/v1/members").status_code == 403
            assert client.get("/api/v1/roles").status_code == 403


def test_the_directory_shows_names_to_read_write_only(
    make_client: Callable[..., TestClient],
    workspace: Account,
    add_member: Callable[..., Account],
) -> None:
    writer = add_member(workspace, role="read_write")
    reader = add_member(workspace, role="read")
    with make_client() as client:
        log_in(client, writer.email)
        entries = client.get("/api/v1/members/directory").json()
    assert {e["email"] for e in entries} == {workspace.email, writer.email, reader.email}
    assert set(entries[0]) == {"id", "name", "email"}  # nothing a picker does not need
    with make_client() as client:
        log_in(client, reader.email)
        assert client.get("/api/v1/members/directory").status_code == 403


def test_roles_are_listed_as_data(manager: TestClient) -> None:
    roles = {r["key"]: r for r in manager.get("/api/v1/roles").json()}
    assert roles["read"]["permissions"] == []
    assert set(roles["read_write"]["permissions"]) == {
        "departments.create",
        "departments.manage",
        "files.send",
        "files.view_sends",
        "members.directory",
        "workspace.rename",
    }
    assert all(r["is_system"] for r in roles.values())


def test_a_role_change_applies_on_the_members_next_request(
    manager: TestClient,
    make_client: Callable[..., TestClient],
    committing_db: Database,
    workspace: Account,
    add_member: Callable[..., Account],
) -> None:
    member = add_member(workspace, role="read")
    with make_client() as theirs:
        log_in(theirs, member.email)
        assert theirs.get("/api/v1/members/directory").status_code == 403

        changed = patch(
            manager,
            f"/api/v1/members/{member.user_id}",
            {"role_id": str(workspace.role_ids["read_write"])},
        )

        assert changed.json()["role"]["name"] == "Editor"
        assert theirs.get("/api/v1/members/directory").status_code == 200  # same session
    assert actions(committing_db, workspace)[-1] == "member.role_changed"


def test_the_creator_cannot_be_demoted_or_removed(
    manager: TestClient,
    workspace: Account,
    add_member: Callable[..., Account],
    committing_db: Database,
    make_client: Callable[..., TestClient],
) -> None:
    demote = patch(
        manager,
        f"/api/v1/members/{workspace.user_id}",
        {"role_id": str(workspace.role_ids["read"])},
    )
    assert demote.json()["code"] == "creator-protected"

    # Even someone the company allowed to manage people cannot touch the creator.
    deputy = add_member(workspace, role="read_write")
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "UPDATE roles SET permissions = permissions || ARRAY['members.manage'] "
                "WHERE id = :r"
            ),
            {"r": workspace.role_ids["read_write"]},
        )
    with make_client() as client:
        log_in(client, deputy.email)
        assert (
            delete(client, f"/api/v1/members/{workspace.user_id}").json()["code"]
            == "creator-protected"
        )
        assert (
            delete(client, f"/api/v1/members/{deputy.user_id}").json()["code"]
            == "cannot-remove-self"
        )


def test_removal_ends_the_members_sessions_at_once(
    manager: TestClient,
    make_client: Callable[..., TestClient],
    committing_db: Database,
    workspace: Account,
    add_member: Callable[..., Account],
) -> None:
    member = add_member(workspace)
    with make_client() as theirs:
        log_in(theirs, member.email)

        assert delete(manager, f"/api/v1/members/{member.user_id}").status_code == 204

        assert theirs.get("/api/v1/me").status_code == 401
    ids = [m["id"] for m in manager.get("/api/v1/members").json()]
    assert str(member.user_id) not in ids
    assert actions(committing_db, workspace)[-1] == "member.removed"
    assert delete(manager, f"/api/v1/members/{member.user_id}").status_code == 404  # already gone


def test_renaming_the_workspace_and_yourself(
    manager: TestClient,
    committing_db: Database,
    workspace: Account,
    make_client: Callable[..., TestClient],
    add_member: Callable[..., Account],
) -> None:
    renamed = patch(manager, "/api/v1/workspace", {"name": "  Hale Ward & Partners  "})
    assert renamed.json()["name"] == "Hale Ward & Partners"
    assert actions(committing_db, workspace)[-1] == "workspace.renamed"

    me = patch(manager, "/api/v1/me", {"name": "Rosa H."})
    assert me.json()["user"]["name"] == "Rosa H."
    assert manager.get("/api/v1/me").json()["workspace"]["name"] == "Hale Ward & Partners"

    reader = add_member(workspace, role="read")
    with make_client() as client:
        log_in(client, reader.email)
        assert patch(client, "/api/v1/workspace", {"name": "Mine now"}).status_code == 403
        assert patch(client, "/api/v1/me", {"name": "Sam"}).status_code == 200


def test_another_workspaces_members_are_not_found(
    manager: TestClient,
    workspace: Account,
    make_workspace: Callable[..., Account],
    add_member: Callable[..., Account],
) -> None:
    other = make_workspace(workspace_name="Baker & Co")
    stranger = add_member(other)

    for response in (
        patch(
            manager,
            f"/api/v1/members/{stranger.user_id}",
            {"role_id": str(workspace.role_ids["read"])},
        ),
        delete(manager, f"/api/v1/members/{stranger.user_id}"),
        delete(manager, f"/api/v1/members/{other.user_id}"),
    ):
        assert response.status_code == 404
    emails = {m["email"] for m in manager.get("/api/v1/members").json()}
    assert stranger.email not in emails and other.email not in emails
    wrong_role = patch(
        manager, f"/api/v1/members/{workspace.user_id}", {"role_id": str(other.role_ids["read"])}
    )
    assert wrong_role.status_code in (409, 422)  # never applied either way
