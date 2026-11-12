"""Log-in, sessions, CSRF and permissions (Phase 2 LLD topics 4, 7, 8)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Annotated, Any

import pytest
from argon2 import PasswordHasher
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.config import Settings
from signora.kernel.db import Database
from signora.kernel.jobs import JobRegistry
from signora.modules.identity_access import Actor, Permission, current_actor, require
from signora.modules.identity_access import jobs as identity_jobs
from signora.modules.identity_access import login as login_service
from signora.modules.identity_access.dependencies import CSRF_COOKIE, SESSION_COOKIE
from signora.modules.identity_access.domain import passwords
from tests.modules.identity_access.conftest import (
    PASSWORD,
    Account,
    csrf_headers,
    log_in,
    unique_email,
)
from tests.support.workers import running_worker, wait_until

LOGIN = "/api/v1/auth/login"


def attempt(client: TestClient, email: str, password: str) -> Any:
    return client.post(LOGIN, json={"email": email, "password": password})


def sessions_of(db: Database, user_id: Any) -> list[Any]:
    with db.unit_of_work() as uow:
        return list(
            uow.session.execute(
                text("SELECT * FROM sessions WHERE user_id = :u"), {"u": user_id}
            ).all()
        )


# --- log-in ------------------------------------------------------------------------------------


def test_log_in_returns_the_user_and_sets_hardened_cookies(
    client: TestClient, make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace(workspace_name="Hale & Ward LLP")

    response = attempt(client, account.email.upper(), PASSWORD)  # emails match case-insensitively

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == account.email
    assert body["workspace"] == {
        "id": str(account.workspace_id),
        "name": "Hale & Ward LLP",
        "logo_url": None,
    }
    assert body["role"]["key"] == "read_write"
    assert body["is_creator"] is True
    assert body["display_role"]["name"] == "Owner"
    assert set(body["permissions"]) == {p.value for p in Permission}

    cookies = {c.split("=", 1)[0]: c for c in response.headers.get_list("set-cookie")}
    session_cookie = cookies[SESSION_COOKIE].lower()
    for flag in ("httponly", "secure", "samesite=lax", "path=/"):
        assert flag in session_cookie
    assert "max-age" not in session_cookie and "expires" not in session_cookie
    assert "domain" not in session_cookie
    csrf_cookie = cookies[CSRF_COOKIE].lower()
    assert "secure" in csrf_cookie and "httponly" not in csrf_cookie

    assert client.get("/api/v1/me").json() == body


def test_unknown_email_and_wrong_password_look_identical(
    client: TestClient, make_workspace: Callable[..., Account], monkeypatch: pytest.MonkeyPatch
) -> None:
    account = make_workspace()
    dummy_checks: list[str] = []
    real = passwords.spend_verification_time

    def recording(password: str) -> None:
        dummy_checks.append(password)
        real(password)

    monkeypatch.setattr(login_service, "spend_verification_time", recording)

    wrong = attempt(client, account.email, "not the password at all")
    unknown = attempt(client, unique_email("nobody"), "not the password at all")

    assert wrong.status_code == unknown.status_code == 401

    def strip(response: Any) -> dict[str, Any]:
        return {k: v for k, v in response.json().items() if k != "request_id"}

    assert strip(wrong) == strip(unknown)
    assert strip(wrong)["code"] == "invalid-credentials"
    assert dummy_checks == ["not the password at all"]  # unknown email still paid for a hash
    assert SESSION_COOKIE not in wrong.cookies


def test_waits_start_after_five_failures_and_block_even_the_right_password(
    client: TestClient, make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace()
    for _ in range(5):
        assert attempt(client, account.email, "wrong password!!").status_code == 401

    blocked = attempt(client, account.email, PASSWORD)

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate-limited"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_unknown_emails_are_throttled_the_same_way(
    client: TestClient,
) -> None:
    nobody = unique_email("nobody")
    for _ in range(5):
        assert attempt(client, nobody, "guess guess guess").status_code == 401
    assert attempt(client, nobody, "guess guess guess").status_code == 429


def test_a_successful_log_in_resets_the_count(
    client: TestClient, make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace()
    for _ in range(4):
        attempt(client, account.email, "wrong password!!")
    log_in(client, account.email)
    for _ in range(4):
        assert attempt(client, account.email, "wrong password!!").status_code == 401


def test_many_failures_from_one_ip_are_refused(
    make_client: Callable[..., TestClient],
    settings: Settings,
    make_workspace: Callable[..., Account],
) -> None:
    account = make_workspace()
    behind_proxy = settings.model_copy(
        update={"api": settings.api.model_copy(update={"trust_proxy_headers": True})}
    )
    attacker = {"X-Forwarded-For": "203.0.113.9"}
    with make_client(behind_proxy, login_ip_limit=3) as client:
        for _ in range(3):
            body = {"email": unique_email("spray"), "password": "leaked password 1"}
            assert client.post(LOGIN, json=body, headers=attacker).status_code == 401
        body = {"email": account.email, "password": PASSWORD}  # another email, right password
        refused = client.post(LOGIN, json=body, headers=attacker)
        other_ip = client.post(LOGIN, json=body, headers={"X-Forwarded-For": "198.51.100.4"})
    assert refused.status_code == 429
    assert other_ip.status_code == 200


def test_a_removed_member_with_the_right_password_is_told_access_was_removed(
    client: TestClient,
    committing_db: Database,
    make_workspace: Callable[..., Account],
    add_member: Callable[..., Account],
) -> None:
    member = add_member(make_workspace(workspace_name="Acme Law"))
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :u"), {"u": member.user_id}
        )

    right = attempt(client, member.email, PASSWORD)
    wrong = attempt(client, member.email, "wrong password!!")

    assert right.status_code == 403
    assert right.json()["code"] == "access-removed"
    assert right.json()["detail"] == (
        "You no longer have access to Acme Law. Ask the owner if you need it back."
    )
    assert wrong.status_code == 401
    assert sessions_of(committing_db, member.user_id) == []


def test_log_in_upgrades_an_outdated_hash(
    client: TestClient, committing_db: Database, make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace()
    weak = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash(PASSWORD)
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE users SET password_hash = :h WHERE id = :u"),
            {"h": weak, "u": account.user_id},
        )

    log_in(client, account.email)

    with committing_db.unit_of_work() as uow:
        stored = uow.session.execute(
            text("SELECT password_hash FROM users WHERE id = :u"), {"u": account.user_id}
        ).scalar_one()
    assert stored != weak
    assert not PasswordHasher().check_needs_rehash(stored)


def test_every_log_in_creates_a_new_session(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    make_workspace: Callable[..., Account],
) -> None:
    account = make_workspace()
    with make_client() as first, make_client() as second:
        log_in(first, account.email)
        log_in(second, account.email)
        assert first.cookies[SESSION_COOKIE] != second.cookies[SESSION_COOKIE]
    rows = sessions_of(committing_db, account.user_id)
    assert len(rows) == 2
    assert all(len(row.id_hash) == 32 for row in rows)  # only digests are stored


# --- sessions ----------------------------------------------------------------------------------


def test_me_needs_a_live_session(
    client: TestClient, committing_db: Database, make_workspace: Callable[..., Account]
) -> None:
    assert client.get("/api/v1/me").json()["code"] == "unauthenticated"
    client.cookies.set(SESSION_COOKIE, "forged-token", domain="testserver")
    assert client.get("/api/v1/me").status_code == 401

    account = make_workspace()
    client.cookies.clear()
    log_in(client, account.email)
    assert client.get("/api/v1/me").status_code == 200

    with committing_db.unit_of_work() as uow:  # idle for longer than 12 hours
        uow.session.execute(
            text(
                "UPDATE sessions SET last_seen_at = now() - interval '12 hours 1 minute' "
                "WHERE user_id = :u"
            ),
            {"u": account.user_id},
        )
    assert client.get("/api/v1/me").status_code == 401


def test_a_deactivated_users_sessions_stop_working_at_once(
    client: TestClient,
    committing_db: Database,
    make_workspace: Callable[..., Account],
    add_member: Callable[..., Account],
) -> None:
    member = add_member(make_workspace())
    log_in(client, member.email)
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :u"), {"u": member.user_id}
        )
    assert client.get("/api/v1/me").status_code == 401


def test_activity_is_written_at_most_every_five_minutes(
    client: TestClient, committing_db: Database, make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace()
    log_in(client, account.email)

    def set_last_seen(ago: str) -> Any:
        with committing_db.unit_of_work() as uow:
            return uow.session.execute(
                text(
                    "UPDATE sessions SET last_seen_at = now() - CAST(:ago AS interval) "
                    "WHERE user_id = :u RETURNING last_seen_at"
                ),
                {"ago": ago, "u": account.user_id},
            ).scalar_one()

    recent = set_last_seen("4 minutes")
    client.get("/api/v1/me")
    assert sessions_of(committing_db, account.user_id)[0].last_seen_at == recent  # not rewritten

    stale = set_last_seen("6 minutes")
    client.get("/api/v1/me")
    assert sessions_of(committing_db, account.user_id)[0].last_seen_at > stale


def test_log_out_ends_the_session_and_clears_the_cookies(
    client: TestClient, committing_db: Database, make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace()
    log_in(client, account.email)

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert sessions_of(committing_db, account.user_id) == []
    cleared = " ".join(response.headers.get_list("set-cookie")).lower()
    assert SESSION_COOKIE.lower() in cleared and "max-age=0" in cleared
    assert client.post("/api/v1/auth/logout").status_code == 204  # already signed out: fine


# --- CSRF and permissions ----------------------------------------------------------------------


@pytest.fixture
def guarded(client: TestClient) -> TestClient:
    router = APIRouter()

    @router.post("/api/v1/test/change")
    def change(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, str]:
        return {"user": str(actor.user_id)}

    @router.get("/api/v1/test/people")
    def people(
        actor: Annotated[Actor, Depends(require(Permission.MEMBERS_MANAGE))],
    ) -> dict[str, bool]:
        return {"ok": True}

    client.app.include_router(router)  # type: ignore[attr-defined]
    return client


def test_state_changes_need_the_signed_csrf_token(
    guarded: TestClient, make_workspace: Callable[..., Account]
) -> None:
    log_in(guarded, make_workspace().email)

    assert guarded.post("/api/v1/test/change").json()["code"] == "csrf-failed"
    assert (
        guarded.post("/api/v1/test/change", headers={"X-CSRF-Token": "0" * 64}).status_code == 403
    )
    assert guarded.post("/api/v1/test/change", headers=csrf_headers(guarded)).status_code == 200


def test_a_csrf_token_from_another_session_is_refused(
    make_client: Callable[..., TestClient], make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace()
    with make_client() as other:
        log_in(other, account.email)
        stolen = csrf_headers(other)
    with make_client() as client:
        router = APIRouter()

        @router.post("/api/v1/test/change")
        def change(actor: Annotated[Actor, Depends(current_actor)]) -> None:
            return None

        client.app.include_router(router)  # type: ignore[attr-defined]
        log_in(client, account.email)
        assert client.post("/api/v1/test/change", headers=stolen).status_code == 403


def test_permissions_come_from_the_role_and_the_creator_has_all(
    guarded: TestClient,
    make_client: Callable[..., TestClient],
    make_workspace: Callable[..., Account],
    add_member: Callable[..., Account],
) -> None:
    workspace = make_workspace()
    member = add_member(workspace, role="read_write")

    log_in(guarded, workspace.email)
    assert guarded.get("/api/v1/test/people").status_code == 200

    guarded.cookies.clear()
    me = log_in(guarded, member.email)
    assert set(me["permissions"]) == {
        "departments.create",
        "departments.manage",
        "documents.send",
        "documents.view_sends",
        "members.directory",
        "workspace.rename",
    }
    assert me["is_creator"] is False
    assert guarded.get("/api/v1/test/people").json()["code"] == "permission-denied"


def test_role_rows_are_data_and_unknown_permissions_are_ignored(
    guarded: TestClient,
    committing_db: Database,
    make_workspace: Callable[..., Account],
    add_member: Callable[..., Account],
) -> None:
    workspace = make_workspace()
    member = add_member(workspace, role="read")
    with committing_db.unit_of_work() as uow:  # a company decides readers may manage people
        uow.session.execute(
            text(
                "UPDATE roles SET permissions = ARRAY['members.manage', 'projects.future'] "
                "WHERE id = :r"
            ),
            {"r": workspace.role_ids["read"]},
        )

    me = log_in(guarded, member.email)

    assert me["permissions"] == ["members.manage"]
    assert guarded.get("/api/v1/test/people").status_code == 200


# --- sweep -------------------------------------------------------------------------------------


def test_the_sweep_deletes_idle_sessions_and_old_tokens(
    client: TestClient,
    committing_db: Database,
    test_db_settings: Any,
    make_workspace: Callable[..., Account],
) -> None:
    account = make_workspace()
    log_in(client, account.email)
    old_token, fresh_token = bytes([1] * 32), bytes([2] * 32)
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "UPDATE sessions SET last_seen_at = now() - interval '13 hours' WHERE user_id = :u"
            ),
            {"u": account.user_id},
        )
        uow.session.execute(
            text("DELETE FROM email_tokens WHERE token_hash IN (:a, :b)"),
            {"a": old_token, "b": fresh_token},
        )
        for digest, expired in ((old_token, "8 days"), (fresh_token, "1 day")):
            uow.session.execute(
                text(
                    "INSERT INTO email_tokens (purpose, email, token_hash, expires_at) "
                    "VALUES ('signup', 'x@example.com', :t, now() - CAST(:ago AS interval))"
                ),
                {"t": digest, "ago": expired},
            )

    reg = JobRegistry()
    recurring = identity_jobs.register(reg)
    recurring = [r.__class__(r.kind, every=timedelta(seconds=1)) for r in recurring]
    with running_worker(committing_db, test_db_settings, reg, recurring=recurring):
        wait_until(lambda: sessions_of(committing_db, account.user_id) == [])

    with committing_db.unit_of_work() as uow:
        left = (
            uow.session.execute(
                text("SELECT token_hash FROM email_tokens WHERE token_hash IN (:a, :b)"),
                {"a": old_token, "b": fresh_token},
            )
            .scalars()
            .all()
        )
    assert [bytes(t) for t in left] == [fresh_token]
