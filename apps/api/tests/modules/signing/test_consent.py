"""Consent to electronic records (Phase 8 LLD §3): after the code, before the document, once per
person, versioned, recorded with the request's address and browser."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.identity_access.conftest import Account
from tests.modules.signing.conftest import Sent, sent_envelope
from tests.modules.signing.test_open import SIGN, open_link, token_for

NO_CODE = {
    "require_email_code": False,
    "reminder_interval_hours": 24,
    "max_reminders": 5,
    "expiry_days": 14,
    "notify_emails": [],
}


@pytest.fixture
def browser(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


def _sent(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    **settings: Any,
) -> Sent:
    return sent_envelope(owner, run, detect, company, settings={**NO_CODE, **settings})


def _consent(browser: TestClient, recipient_id: str, version: str = "esign-disclosure-v1") -> Any:
    return browser.post(
        f"{SIGN}/{recipient_id}/consent",
        json={"disclosure_version": version},
        headers={"User-Agent": "Firefox/159"},
    )


def test_consent_is_given_once_and_kept_with_its_version(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    browser: TestClient,
    make_client: Callable[..., TestClient],
    committing_db: Database,
) -> None:
    sent = _sent(owner, run, detect, company)
    signer = str(sent.recipient("signer")["id"])
    assert open_link(browser, token_for(signer)).json()["next"] == "consent"

    disclosure = browser.get(f"{SIGN}/{signer}").json()["disclosure"]
    assert disclosure["version"] == "esign-disclosure-v1"
    assert disclosure["agreement"] == "I agree to use electronic records and signatures."
    assert [p["title"] for p in disclosure["paragraphs"]] == [
        "What this covers",
        "A paper copy",
        "Withdrawing consent",
        "What you need",
    ]
    assert company.email in disclosure["paragraphs"][1]["text"]  # whom to ask for paper

    given = _consent(browser, signer)
    assert given.status_code == 200, given.text
    assert given.json()["next"] == "sign"
    assert _consent(browser, signer).json()["next"] == "sign"  # a repeat changes nothing

    with make_client() as laptop:  # consent belongs to the person, not the browser
        assert open_link(laptop, token_for(signer)).json()["next"] == "sign"

    with committing_db.unit_of_work() as uow:
        row = uow.session.execute(
            text(
                "SELECT disclosure_version, user_agent FROM signing_consents "
                "WHERE recipient_id = :r"
            ),
            {"r": signer},
        ).one()
        consented = uow.session.execute(
            text(
                "SELECT count(*) FROM audit_events WHERE subject_id = :e "
                "AND action = 'signing.consented'"
            ),
            {"e": sent.id},
        ).scalar_one()
    assert tuple(row) == ("esign-disclosure-v1", "Firefox/159")
    assert consented == 1


def test_the_code_comes_before_consent(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    browser: TestClient,
) -> None:
    sent = _sent(owner, run, detect, company, require_email_code=True)
    signer = str(sent.recipient("signer")["id"])
    open_link(browser, token_for(signer))

    refused = _consent(browser, signer)

    assert (refused.status_code, refused.json()["code"]) == (403, "verify-first")


def test_a_changed_disclosure_is_read_again(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    browser: TestClient,
) -> None:
    signer = str(_sent(owner, run, detect, company).recipient("signer")["id"])
    open_link(browser, token_for(signer))

    stale = _consent(browser, signer, version="esign-disclosure-v0")

    assert (stale.status_code, stale.json()["code"]) == (409, "disclosure-changed")
    assert browser.get(f"{SIGN}/{signer}").json()["next"] == "consent"
