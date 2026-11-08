"""Email-first sign-up (Phase 2 LLD topic 1)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.identity_access.conftest import (
    PASSWORD,
    Account,
    idempotency_key,
    latest_email,
    link_token,
    log_in,
    unique_email,
)

SIGNUP = "/api/v1/auth/signup"


def start(client: TestClient, email: str) -> Any:
    return client.post(SIGNUP, json={"email": email})


def complete(client: TestClient, token: str, **overrides: Any) -> Any:
    body = {
        "token": token,
        "workspace_name": "Hale & Ward LLP",
        "name": "Rosa Hale",
        "password": PASSWORD,
    }
    body.update(overrides)
    return client.post(f"{SIGNUP}/complete", json=body, headers=idempotency_key())


def signup_jobs(db: Database, email: str) -> int:
    with db.unit_of_work() as uow:
        return int(
            uow.session.execute(
                text(
                    "SELECT count(*) FROM jobs WHERE kind = 'identity.signup_request' "
                    "AND payload->>'email' = :e"
                ),
                {"e": email},
            ).scalar_one()
        )


def test_the_answer_is_the_same_for_new_registered_and_throttled_emails(
    client: TestClient, committing_db: Database, make_workspace: Callable[..., Account]
) -> None:
    new, registered = unique_email("new"), make_workspace().email

    answers = [start(client, new), start(client, registered), start(client, new)]  # 3rd throttled

    assert {r.status_code for r in answers} == {202}
    assert {str(r.json()) for r in answers} == {"{'status': 'check_email'}"}
    assert signup_jobs(committing_db, new) == 1  # the throttled repeat queued nothing
    assert signup_jobs(committing_db, registered) == 1


def test_a_malformed_email_is_a_validation_error(client: TestClient) -> None:
    response = start(client, "not an email")
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "email"


@pytest.mark.usefixtures("identity_worker")
def test_a_registered_email_gets_a_log_in_reminder_not_a_link(
    client: TestClient, committing_db: Database, make_workspace: Callable[..., Account]
) -> None:
    registered = make_workspace().email
    start(client, registered)

    message = latest_email(committing_db, registered)

    assert message.category == "auth.signup_existing"
    assert "You already have an account." in message.text_body
    assert "#" not in message.text_body  # no token of any kind


@pytest.mark.usefixtures("identity_worker")
def test_the_full_flow_creates_the_workspace_and_lets_the_creator_log_in(
    client: TestClient, committing_db: Database
) -> None:
    email = unique_email("founder")
    start(client, email.upper())  # stored and matched in normal form
    message = latest_email(committing_db, email)
    assert message.category == "auth.signup_verify"
    token = link_token(message, "/signup/verify")

    assert client.post(f"{SIGNUP}/verify", json={"token": token}).json() == {"email": email}
    created = complete(client, token)
    assert created.status_code == 201
    assert created.json() == {"email": email}
    assert "set-cookie" not in created.headers  # no session from completion (LLD §1.2)

    me = log_in(client, email)
    assert me["workspace"]["name"] == "Hale & Ward LLP"
    assert me["user"]["name"] == "Rosa Hale"
    assert me["is_creator"] is True
    with committing_db.unit_of_work() as uow:
        actions = (
            uow.session.execute(
                text("SELECT action FROM audit_events WHERE workspace_id = :w ORDER BY seq"),
                {"w": me["workspace"]["id"]},
            )
            .scalars()
            .all()
        )
        roles = (
            uow.session.execute(
                text("SELECT key FROM roles WHERE workspace_id = :w ORDER BY key"),
                {"w": me["workspace"]["id"]},
            )
            .scalars()
            .all()
        )
    assert actions == ["workspace.created", "member.joined"]
    assert roles == ["read", "read_write"]

    # The link is used up.
    assert client.post(f"{SIGNUP}/verify", json={"token": token}).json()["code"] == "link-expired"
    assert complete(client, token).status_code == 410


@pytest.mark.usefixtures("identity_worker")
def test_a_retried_completion_replays_instead_of_failing(
    client: TestClient, committing_db: Database
) -> None:
    email = unique_email("retry")
    start(client, email)
    token = link_token(latest_email(committing_db, email), "/signup/verify")
    body = {"token": token, "workspace_name": "Acme", "name": "Rosa", "password": PASSWORD}
    key = idempotency_key()

    first = client.post(f"{SIGNUP}/complete", json=body, headers=key)
    again = client.post(f"{SIGNUP}/complete", json=body, headers=key)  # the reply was lost

    assert first.status_code == again.status_code == 201
    assert again.json() == first.json()


@pytest.mark.usefixtures("identity_worker")
def test_a_weak_password_is_refused_and_the_link_still_works(
    client: TestClient, committing_db: Database
) -> None:
    email = unique_email("weak")
    start(client, email)
    token = link_token(latest_email(committing_db, email), "/signup/verify")

    weak = complete(client, token, password="password1234")  # noqa: S106 - a known-common one

    assert weak.status_code == 422
    assert weak.json()["errors"] == [
        {"field": "password", "message": "This password is too common. Choose another."}
    ]
    assert complete(client, token).status_code == 201


def test_unknown_and_expired_links_look_the_same(
    client: TestClient, committing_db: Database
) -> None:
    from signora.modules.identity_access.domain.tokens import issue_token

    expired = issue_token()
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "INSERT INTO email_tokens (purpose, email, token_hash, expires_at) "
                "VALUES ('signup', :e, :h, now() - interval '1 second')"
            ),
            {"e": unique_email("late"), "h": expired.digest},
        )

    unknown = client.post(f"{SIGNUP}/verify", json={"token": "x" * 43})
    late = client.post(f"{SIGNUP}/verify", json={"token": expired.value})

    assert unknown.status_code == late.status_code == 410
    assert unknown.json()["title"] == late.json()["title"]


@pytest.mark.usefixtures("identity_worker")
def test_two_links_completed_at_once_create_one_account(
    make_client: Callable[..., TestClient], committing_db: Database
) -> None:
    email = unique_email("race")
    with make_client() as client:
        start(client, email)
    first = link_token(latest_email(committing_db, email), "/signup/verify")
    with committing_db.unit_of_work() as uow:  # a second link, as if requested again later
        from signora.modules.identity_access.domain.tokens import issue_token

        second_token = issue_token()
        uow.session.execute(
            text(
                "INSERT INTO email_tokens (purpose, email, token_hash, expires_at) "
                "VALUES ('signup', :e, :h, now() + interval '1 hour')"
            ),
            {"e": email, "h": second_token.digest},
        )

    results: list[int] = []
    barrier = threading.Barrier(2)

    # One app with one event loop, as in production (uvicorn); the two plain-def handlers run
    # concurrently on its thread pool, so the database race is real.
    with make_client() as client:

        def finish(token: str) -> None:
            barrier.wait()
            results.append(complete(client, token).status_code)

        threads = [threading.Thread(target=finish, args=(t,)) for t in (first, second_token.value)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert sorted(results) in ([201, 409], [201, 410])  # one wins; the other is told why
    with committing_db.unit_of_work() as uow:
        users = uow.session.execute(
            text("SELECT count(*) FROM users WHERE email = :e"), {"e": email}
        ).scalar_one()
    assert users == 1


@pytest.mark.usefixtures("identity_worker")
def test_emails_carry_the_link_after_the_fragment_marker(
    client: TestClient, committing_db: Database
) -> None:
    email = unique_email("fragment")
    start(client, email)

    message = latest_email(committing_db, email)

    assert "/signup/verify#" in message.text_body
    assert "/signup/verify?" not in message.text_body  # never in a query string
