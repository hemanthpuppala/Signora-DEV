"""Password reset and change (Phase 2 LLD topic 2, §8.2)."""

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
    latest_email,
    link_token,
    log_in,
    unique_email,
)
from tests.support.workers import wait_until

NEW_PASSWORD = "a brand new passphrase"  # noqa: S105 - test value
FORGOT = "/api/v1/auth/password/forgot"


def forgot(client: TestClient, email: str) -> Any:
    return client.post(FORGOT, json={"email": email})


def reset(client: TestClient, token: str, password: str = NEW_PASSWORD) -> Any:
    return client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": password},
        headers=idempotency_key(),
    )


def reset_jobs(db: Database, email: str) -> int:
    with db.unit_of_work() as uow:
        return int(
            uow.session.execute(
                text(
                    "SELECT count(*) FROM jobs WHERE kind = 'identity.password_reset_request' "
                    "AND payload->>'email' = :e AND status = 'succeeded'"
                ),
                {"e": email},
            ).scalar_one()
        )


def sessions(db: Database, account: Account) -> int:
    with db.unit_of_work() as uow:
        return int(
            uow.session.execute(
                text("SELECT count(*) FROM sessions WHERE user_id = :u"), {"u": account.user_id}
            ).scalar_one()
        )


def test_forgot_answers_the_same_for_every_address(
    client: TestClient, make_workspace: Callable[..., Account]
) -> None:
    answers = [forgot(client, make_workspace().email), forgot(client, unique_email("ghost"))]
    assert [(r.status_code, r.json()) for r in answers] == [
        (202, {"status": "check_email"}),
        (202, {"status": "check_email"}),
    ]


@pytest.mark.usefixtures("identity_worker")
def test_unknown_and_removed_addresses_get_nothing(
    client: TestClient,
    committing_db: Database,
    make_workspace: Callable[..., Account],
    add_member: Callable[..., Account],
) -> None:
    ghost = unique_email("ghost")
    removed = add_member(make_workspace())
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :u"), {"u": removed.user_id}
        )

    forgot(client, ghost)
    forgot(client, removed.email)
    wait_until(
        lambda: reset_jobs(committing_db, ghost) == reset_jobs(committing_db, removed.email) == 1
    )

    assert emails_to(committing_db, ghost) == []
    assert emails_to(committing_db, removed.email) == []


@pytest.mark.usefixtures("identity_worker")
def test_reset_sets_the_password_and_signs_out_everywhere(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    make_workspace: Callable[..., Account],
) -> None:
    account = make_workspace()
    with make_client() as laptop, make_client() as phone:
        log_in(laptop, account.email)
        log_in(phone, account.email)
        assert sessions(committing_db, account) == 2

        forgot(phone, account.email)
        message = latest_email(committing_db, account.email)
        assert message.category == "auth.password_reset"
        token = link_token(message, "/reset-password")
        verified = phone.post("/api/v1/auth/password/reset/verify", json={"token": token})
        assert verified.json() == {"email": account.email}

        done = reset(phone, token)

        assert done.status_code == 200
        assert done.json() == {"email": account.email}
        assert sessions(committing_db, account) == 0
        assert laptop.get("/api/v1/me").status_code == 401
        assert (
            phone.post(
                "/api/v1/auth/login", json={"email": account.email, "password": PASSWORD}
            ).status_code
            == 401
        )
        log_in(phone, account.email, NEW_PASSWORD)

    categories = [m.category for m in emails_to(committing_db, account.email)]
    assert categories[-1] == "auth.password_changed"
    assert reset(make_client(), token).status_code == 410  # single use


@pytest.mark.usefixtures("identity_worker")
def test_reset_links_expire_after_thirty_minutes(
    client: TestClient, committing_db: Database, make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace()
    forgot(client, account.email)
    token = link_token(latest_email(committing_db, account.email), "/reset-password")
    with committing_db.unit_of_work() as uow:
        expiry = uow.session.execute(
            text(
                "SELECT expires_at - created_at FROM email_tokens "
                "WHERE email = :e AND purpose = 'password_reset'"
            ),
            {"e": account.email},
        ).scalar_one()
        uow.session.execute(
            text(
                "UPDATE email_tokens SET expires_at = now() - interval '1 second' WHERE email = :e"
            ),
            {"e": account.email},
        )

    assert expiry.total_seconds() == 30 * 60
    assert reset(client, token).status_code == 410


@pytest.mark.usefixtures("identity_worker")
def test_reset_refuses_a_weak_password_and_keeps_the_link(
    client: TestClient, committing_db: Database, make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace()
    forgot(client, account.email)
    token = link_token(latest_email(committing_db, account.email), "/reset-password")

    weak = reset(client, token, "too short")

    assert weak.status_code == 422
    assert weak.json()["errors"][0]["field"] == "password"
    assert reset(client, token).status_code == 200


# --- change password while signed in -----------------------------------------------------------


def change(client: TestClient, current: str, new: str = NEW_PASSWORD) -> Any:
    return client.post(
        "/api/v1/me/password",
        json={"current_password": current, "new_password": new},
        headers={**csrf_headers(client), **idempotency_key()},
    )


def test_change_needs_the_current_password_and_keeps_this_session_only(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    make_workspace: Callable[..., Account],
) -> None:
    account = make_workspace()
    with make_client() as here, make_client() as elsewhere:
        log_in(here, account.email)
        log_in(elsewhere, account.email)

        wrong = change(here, "not my password")
        assert wrong.status_code == 422
        assert wrong.json()["errors"][0]["field"] == "current_password"

        assert change(here, PASSWORD).status_code == 200
        assert here.get("/api/v1/me").status_code == 200
        assert elsewhere.get("/api/v1/me").status_code == 401

    assert emails_to(committing_db, account.email)[-1].category == "auth.password_changed"


def test_change_needs_the_csrf_token(
    client: TestClient, make_workspace: Callable[..., Account]
) -> None:
    log_in(client, make_workspace().email)
    response = client.post(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=idempotency_key(),
    )
    assert response.json()["code"] == "csrf-failed"


def test_guessing_the_current_password_is_throttled(
    client: TestClient, make_workspace: Callable[..., Account]
) -> None:
    log_in(client, make_workspace().email)
    for _ in range(5):
        assert change(client, "guess guess guess").status_code == 422
    assert change(client, PASSWORD).status_code == 429
