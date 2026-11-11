"""Opening a signing link (Phase 8 LLD §1): a link becomes a browser session; closed, replaced and
forged links answer alike; each request acts only for the person its grant names."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.config import get_settings
from signora.kernel.db import Database
from signora.modules.envelopes.links import link_key, make_token
from tests.modules.documents.conftest import csrf_headers
from tests.modules.envelopes.conftest import sendable
from tests.modules.envelopes.test_send import request_for, send
from tests.modules.identity_access.conftest import Account
from tests.modules.signing.conftest import Sent, sent_envelope

ENVELOPES = "/api/v1/envelopes"
SIGN = "/api/v1/sign"
COOKIE = "__Host-signora_sign"


def token_for(recipient_id: str, version: int = 1) -> str:
    key = link_key(get_settings().app.secret_key.get_secret_value())
    return make_token(key, uuid.UUID(recipient_id), version)


def open_link(browser: TestClient, token: str) -> Any:
    return browser.post(f"{SIGN}/open", json={"token": token})


def closed(answer: Any) -> bool:
    """The one answer for every link that cannot be used (§1.2)."""
    body = answer.json()
    return answer.status_code == 404 and (body["code"], body["title"]) == (
        "link-closed",
        "This request is no longer open. Nothing more is needed from you",
    )


@pytest.fixture
def browser(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    """The signer's own browser: no console session."""
    with make_client() as test_client:
        yield test_client


@pytest.fixture
def sent(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> Sent:
    return sent_envelope(owner, run, detect, company)


def _opened_events(db: Database, envelope_id: str) -> int:
    with db.unit_of_work() as uow:
        return int(
            uow.session.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE action = 'signing.opened' "
                    "AND subject_id = :e AND chain_kind = 'envelope' AND actor_type = 'recipient'"
                ),
                {"e": envelope_id},
            ).scalar_one()
        )


def test_opening_makes_a_session_records_opened_once_and_says_what_is_next(
    sent: Sent, browser: TestClient, owner: TestClient, committing_db: Database
) -> None:
    signer = sent.recipient("signer")

    first = open_link(browser, token_for(signer["id"]))

    assert first.status_code == 200, first.text
    assert first.json() == {"recipient_id": signer["id"], "next": "verify"}
    cookie = first.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert all(part in cookie.lower() for part in ("httponly", "secure", "samesite=strict"))
    assert "max-age" not in cookie.lower() and "expires" not in cookie.lower()  # browser session
    assert first.headers["cache-control"] == "no-store"

    again = open_link(browser, token_for(signer["id"]))  # the same browser, the same link
    assert again.status_code == 200
    assert "set-cookie" not in again.headers  # the live session is kept

    state = browser.get(f"{SIGN}/{signer['id']}")
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["name"] == "Maya Chen"
    assert body["email_masked"].startswith("m•••@") and body["email_masked"].endswith("example.com")
    assert (body["next"], body["signed_at"]) == ("verify", None)
    assert body["title"] == sent.envelope["title"]

    envelope = owner.get(f"{ENVELOPES}/{sent.id}").json()
    assert envelope["status"] == "opened"
    assert envelope["recipients"][0]["status"] == "opened"
    assert _opened_events(committing_db, sent.id) == 1


def test_without_an_email_code_the_next_step_is_consent(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    browser: TestClient,
) -> None:
    settings = {
        "require_email_code": False,
        "reminder_interval_hours": 24,
        "max_reminders": 5,
        "expiry_days": 14,
        "notify_emails": [],
    }
    sent = sent_envelope(owner, run, detect, company, settings=settings)

    opened = open_link(browser, token_for(sent.recipient("signer")["id"]))

    assert opened.json()["next"] == "consent"


def test_every_link_that_cannot_be_used_answers_the_same(
    sent: Sent, browser: TestClient, owner: TestClient
) -> None:
    signer, firm = sent.recipient("signer"), sent.recipient("countersigner")
    genuine = token_for(signer["id"])
    answers = [
        open_link(browser, genuine[:-2] + ("AA" if not genuine.endswith("AA") else "BB")),
        open_link(browser, "not-a-token"),
        open_link(browser, token_for(signer["id"], version=2)),  # a version never issued
        open_link(browser, token_for(str(uuid.uuid4()))),  # nobody
        open_link(browser, token_for(firm["id"])),  # countersigners sign in Signora (§7)
    ]
    assert all(closed(answer) for answer in answers), [a.text for a in answers]
    assert all("set-cookie" not in answer.headers for answer in answers)

    cancelled = owner.post(f"{ENVELOPES}/{sent.id}/cancel", headers=csrf_headers(owner))
    assert cancelled.status_code == 200, cancelled.text
    assert closed(open_link(browser, genuine))


def test_an_open_page_closes_at_its_next_request_once_the_envelope_closes(
    sent: Sent, browser: TestClient, committing_db: Database
) -> None:
    signer = sent.recipient("signer")
    assert open_link(browser, token_for(signer["id"])).status_code == 200

    with committing_db.unit_of_work() as uow:  # past its expiry, before Phase 10 moves its status
        uow.session.execute(
            text("UPDATE envelopes SET expires_at = now() - interval '1 minute' WHERE id = :e"),
            {"e": sent.id},
        )

    assert closed(browser.get(f"{SIGN}/{signer['id']}"))
    assert closed(open_link(browser, token_for(signer["id"])))


def test_a_corrected_email_ends_the_old_grant_and_the_new_link_opens(
    sent: Sent, browser: TestClient, owner: TestClient
) -> None:
    signer = sent.recipient("signer")
    assert open_link(browser, token_for(signer["id"])).status_code == 200

    corrected = owner.patch(
        f"{ENVELOPES}/{sent.id}/recipients/{signer['id']}",
        json={"email": f"maya-{uuid.uuid4().hex[:8]}@example.org"},
        headers=csrf_headers(owner),
    )
    assert corrected.status_code == 200, corrected.text

    assert closed(browser.get(f"{SIGN}/{signer['id']}"))
    assert closed(open_link(browser, token_for(signer["id"], version=1)))
    reopened = open_link(browser, token_for(signer["id"], version=2))
    assert reopened.status_code == 200, reopened.text
    assert browser.get(f"{SIGN}/{signer['id']}").status_code == 200


def test_a_request_acts_only_for_a_person_opened_in_this_browser(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    make_client: Callable[..., TestClient],
) -> None:
    doc = sendable(owner, run, detect)
    maya, leo = (
        send(owner, doc, request_for(owner, doc, company)).json()["recipients"][0] for _ in range(2)
    )

    with make_client() as one, make_client() as other:
        assert open_link(one, token_for(maya["id"])).status_code == 200
        assert open_link(one, token_for(leo["id"])).status_code == 200  # same browser, two people
        assert one.get(f"{SIGN}/{maya['id']}").json()["recipient_id"] == maya["id"]
        assert one.get(f"{SIGN}/{leo['id']}").json()["recipient_id"] == leo["id"]

        assert other.get(f"{SIGN}/{maya['id']}").json()["code"] == "session-ended"  # no cookie
        assert open_link(other, token_for(leo["id"])).status_code == 200
        ended = other.get(f"{SIGN}/{maya['id']}")  # a session, but not Maya's grant
        assert (ended.status_code, ended.json()["code"]) == (401, "session-ended")


def test_a_session_ends_after_its_idle_time(
    sent: Sent, browser: TestClient, committing_db: Database
) -> None:
    signer = sent.recipient("signer")
    assert open_link(browser, token_for(signer["id"])).status_code == 200
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "UPDATE signing_sessions SET last_seen_at = now() - interval '31 minutes' "
                "WHERE id_hash IN (SELECT session_hash FROM signing_grants WHERE recipient_id = :r)"
            ),
            {"r": signer["id"]},
        )

    ended = browser.get(f"{SIGN}/{signer['id']}")
    assert (ended.status_code, ended.json()["code"]) == (401, "session-ended")
    reopened = open_link(browser, token_for(signer["id"]))
    assert "set-cookie" in reopened.headers  # a new session
    assert browser.get(f"{SIGN}/{signer['id']}").status_code == 200
