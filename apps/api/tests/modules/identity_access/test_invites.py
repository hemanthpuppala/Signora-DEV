"""Invites (Phase 2 LLD topic 6)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.identity_access.conftest import (
    PASSWORD,
    Account,
    csrf_headers,
    emails_to,
    idempotency_key,
    link_token,
    log_in,
    unique_email,
)

INVITES = "/api/v1/invites"
RETURNING_PASSWORD = "a whole new passphrase"  # noqa: S105 - test value


def invite(client: TestClient, email: str, role_id: Any) -> Any:
    return client.post(
        INVITES,
        json={"email": email, "role_id": str(role_id)},
        headers={**csrf_headers(client), **idempotency_key()},
    )


def accept(
    client: TestClient, token: str, name: str = "Sam Iqbal", password: str = PASSWORD
) -> Any:
    return client.post(
        f"{INVITES}/accept",
        json={"token": token, "name": name, "password": password},
        headers=idempotency_key(),
    )


def newest_token(db: Database, email: str) -> str:
    return link_token(emails_to(db, email)[-1], "/invite")


@pytest.fixture
def creator(client: TestClient, make_workspace: Callable[..., Account]) -> Account:
    account = make_workspace(workspace_name="Hale & Ward LLP")
    log_in(client, account.email)
    return account


def test_an_invitee_joins_with_the_chosen_role_and_is_audited(
    client: TestClient,
    make_client: Callable[..., TestClient],
    committing_db: Database,
    creator: Account,
) -> None:
    email = unique_email("sam")

    created = invite(client, email.upper(), creator.role_ids["read"])

    assert created.status_code == 201
    body = created.json()
    assert body["email"] == email
    assert body["role"]["name"] == "Read"
    assert body["invited_by_name"] == "Rosa Hale"
    message = emails_to(committing_db, email)[-1]
    assert message.category == "auth.invite"
    assert "Rosa Hale invited you to Hale & Ward LLP" in message.subject
    token = newest_token(committing_db, email)

    with make_client() as invitee:
        details = invitee.post(f"{INVITES}/verify", json={"token": token}).json()
        assert details == {
            "email": email,
            "workspace_name": "Hale & Ward LLP",
            "role_name": "Read",
            "inviter_name": "Rosa Hale",
        }
        assert accept(invitee, token).status_code == 201
        me = log_in(invitee, email)
    assert me["workspace"]["id"] == str(creator.workspace_id)
    assert me["role"]["key"] == "read"
    assert me["permissions"] == []
    assert client.get(INVITES).json() == []  # no longer pending

    with committing_db.unit_of_work() as uow:
        actions = (
            uow.session.execute(
                text("SELECT action FROM audit_events WHERE workspace_id = :w ORDER BY seq"),
                {"w": creator.workspace_id},
            )
            .scalars()
            .all()
        )
    assert actions[-2:] == ["invite.created", "member.joined"]


def test_inviting_a_current_member_says_so(
    client: TestClient, creator: Account, add_member: Callable[..., Account]
) -> None:
    member = add_member(creator)
    response = invite(client, member.email, creator.role_ids["read"])
    assert response.status_code == 409
    assert response.json()["code"] == "already-member"


def test_inviting_again_is_a_resend_that_kills_the_old_link(
    client: TestClient,
    make_client: Callable[..., TestClient],
    committing_db: Database,
    creator: Account,
) -> None:
    email = unique_email("again")
    first = invite(client, email, creator.role_ids["read"]).json()
    old = newest_token(committing_db, email)
    second = invite(client, email, creator.role_ids["read_write"]).json()
    new = newest_token(committing_db, email)

    assert first["id"] == second["id"]  # still one pending invite
    assert second["role"]["name"] == "Read/write"
    with make_client() as invitee:
        assert accept(invitee, old).status_code == 410
        assert accept(invitee, new).status_code == 201


def test_an_email_of_another_workspace_looks_invited_but_can_never_join(
    client: TestClient,
    make_client: Callable[..., TestClient],
    committing_db: Database,
    creator: Account,
    make_workspace: Callable[..., Account],
) -> None:
    elsewhere = make_workspace(workspace_name="Baker & Co").email
    fresh = unique_email("fresh")

    taken = invite(client, elsewhere, creator.role_ids["read"])
    normal = invite(client, fresh, creator.role_ids["read"])

    assert taken.status_code == normal.status_code == 201
    assert taken.json().keys() == normal.json().keys()
    blocked = emails_to(committing_db, elsewhere)[-1]
    assert blocked.category == "auth.invite_blocked"
    assert "#" not in blocked.text_body  # no link to accept


def test_a_removed_member_is_restored_by_accepting_a_new_invite(
    client: TestClient,
    make_client: Callable[..., TestClient],
    committing_db: Database,
    creator: Account,
    add_member: Callable[..., Account],
) -> None:
    member = add_member(creator, role="read")
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :u"), {"u": member.user_id}
        )

    invite(client, member.email, creator.role_ids["read_write"])
    with make_client() as returning:
        assert (
            accept(
                returning,
                newest_token(committing_db, member.email),
                password=RETURNING_PASSWORD,
            ).status_code
            == 201
        )
        me = log_in(returning, member.email, RETURNING_PASSWORD)
    assert me["user"]["id"] == str(member.user_id)  # the same user, history intact
    assert me["role"]["key"] == "read_write"


def test_revoke_kills_the_link_and_is_idempotent(
    client: TestClient,
    make_client: Callable[..., TestClient],
    committing_db: Database,
    creator: Account,
) -> None:
    created = invite(client, unique_email("revoked"), creator.role_ids["read"]).json()
    token = newest_token(committing_db, created["email"])

    for _ in range(2):
        assert (
            client.delete(f"{INVITES}/{created['id']}", headers=csrf_headers(client)).status_code
            == 204
        )
    with make_client() as invitee:
        assert accept(invitee, token).status_code == 410


def test_resend_issues_a_new_link_at_most_once_a_minute(
    client: TestClient,
    make_client: Callable[..., TestClient],
    committing_db: Database,
    creator: Account,
) -> None:
    created = invite(client, unique_email("resend"), creator.role_ids["read"]).json()
    old = newest_token(committing_db, created["email"])
    url = f"{INVITES}/{created['id']}/resend"

    resent = client.post(url, headers={**csrf_headers(client), **idempotency_key()})
    again = client.post(url, headers={**csrf_headers(client), **idempotency_key()})

    assert resent.status_code == 200
    assert again.status_code == 429
    with make_client() as invitee:
        assert accept(invitee, old).status_code == 410
        assert accept(invitee, newest_token(committing_db, created["email"])).status_code == 201


def test_two_companies_inviting_one_new_email_the_first_acceptance_wins(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    make_workspace: Callable[..., Account],
) -> None:
    email = unique_email("popular")
    tokens = []
    for name in ("Acme", "Baker"):
        workspace = make_workspace(workspace_name=name)
        with make_client() as manager:
            log_in(manager, workspace.email)
            invite(manager, email, workspace.role_ids["read"])
        tokens.append(newest_token(committing_db, email))

    with make_client() as invitee:
        assert accept(invitee, tokens[0]).status_code == 201
        second = accept(invitee, tokens[1])
    assert second.status_code == 409
    assert second.json()["code"] == "email-in-other-workspace"


def test_managing_invites_needs_members_manage(
    make_client: Callable[..., TestClient], creator: Account, add_member: Callable[..., Account]
) -> None:
    member = add_member(creator, role="read_write")
    with make_client() as client:
        log_in(client, member.email)
        assert client.get(INVITES).status_code == 403
        assert invite(client, unique_email("x"), creator.role_ids["read"]).status_code == 403


def test_another_workspaces_role_or_invite_is_not_found(
    client: TestClient, creator: Account, make_workspace: Callable[..., Account]
) -> None:
    other = make_workspace(workspace_name="Baker & Co")

    wrong_role = invite(client, unique_email("x"), other.role_ids["read"])
    assert wrong_role.status_code == 422
    assert wrong_role.json()["errors"][0]["field"] == "role_id"

    with TestClient(client.app, base_url="https://testserver") as other_client:
        log_in(other_client, other.email)
        theirs = invite(other_client, unique_email("theirs"), other.role_ids["read"]).json()
    for response in (
        client.delete(f"{INVITES}/{theirs['id']}", headers=csrf_headers(client)),
        client.post(
            f"{INVITES}/{theirs['id']}/resend",
            headers={**csrf_headers(client), **idempotency_key()},
        ),
    ):
        assert response.status_code == 404


def test_the_workspace_invite_limit(
    make_client: Callable[..., TestClient], make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace()
    with make_client(invites_per_hour=2) as client:
        log_in(client, account.email)
        codes = [
            invite(client, unique_email("n"), account.role_ids["read"]).status_code
            for _ in range(3)
        ]
    assert codes == [201, 201, 429]
