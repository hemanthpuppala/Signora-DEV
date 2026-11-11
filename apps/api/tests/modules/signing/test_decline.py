"""Decline (Phase 8 LLD §8): final, with a reason, for everyone; the sender told why, the others
told it is over, a countersigner whose turn never came told nothing."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.identity_access.conftest import Account, idempotency_key
from tests.modules.signing.conftest import Sent, signable_envelope
from tests.modules.signing.test_consent import NO_CODE
from tests.modules.signing.test_document import _ready
from tests.modules.signing.test_open import ENVELOPES, SIGN, open_link, token_for
from tests.modules.signing.test_submit import _fill, _submit

NOTIFY = {**NO_CODE, "notify_emails": ["desk@firm.example"]}


@pytest.fixture
def browser(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


def _decline(
    browser: TestClient, signer: str, reason: str, key: dict[str, str] | None = None
) -> Any:
    return browser.post(
        f"{SIGN}/{signer}/decline", json={"reason": reason}, headers=key or idempotency_key()
    )


def _mail(db: Database, envelope_title: str) -> list[tuple[str, str, str]]:
    with db.unit_of_work() as uow:
        rows = uow.session.execute(
            text(
                "SELECT to_address, subject, text_body FROM email_messages "
                "WHERE category = 'sign_declined' AND subject LIKE :t ORDER BY to_address"
            ),
            {"t": f"%{envelope_title}%"},
        ).all()
    return [(row.to_address, row.subject, row.text_body or "") for row in rows]


def test_a_decline_closes_the_envelope_and_tells_the_sender_why(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    browser: TestClient,
    committing_db: Database,
) -> None:
    sent = signable_envelope(owner, run, detect, company, settings=NOTIFY)
    signer = _ready(browser, sent)

    assert _decline(browser, signer, "   ").status_code == 422
    key = idempotency_key()
    reason = " I'd like to discuss the fee first. "
    declined = _decline(browser, signer, reason, key)

    assert declined.status_code == 200, declined.text
    assert _decline(browser, signer, reason, key).json() == {"declined": True}  # a replay
    envelope = owner.get(f"{ENVELOPES}/{sent.id}").json()
    assert envelope["status"] == "declined"
    assert envelope["recipients"][0]["status"] == "declined"
    assert browser.get(f"{SIGN}/{signer}").json()["code"] == "link-closed"
    assert open_link(browser, token_for(signer)).json()["code"] == "link-closed"

    mail = _mail(committing_db, envelope["title"])
    told = {to: (subject, body) for to, subject, body in mail}
    assert set(told) == {company.email, "desk@firm.example"}  # the countersigner's turn never came
    subject, body = told[company.email]
    assert subject == f"Maya Chen declined {envelope['title']}"
    assert "I'd like to discuss the fee first." in body


def test_someone_who_signed_cannot_decline(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    browser: TestClient,
) -> None:
    sent = signable_envelope(owner, run, detect, company, settings=NO_CODE)
    signer = _ready(browser, sent)
    _fill(browser, signer)
    assert _submit(browser, signer).status_code == 200

    late = _decline(browser, signer, "Changed my mind")

    assert (late.status_code, late.json()["code"]) == (409, "already-signed")


def test_the_code_comes_before_a_decline(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    browser: TestClient,
) -> None:
    coded = signable_envelope(
        owner, run, detect, company, settings={**NO_CODE, "require_email_code": True}
    )
    signer = str(coded.recipient("signer")["id"])
    open_link(browser, token_for(signer))

    early = _decline(browser, signer, "Not me")

    assert (early.status_code, early.json()["code"]) == (403, "verify-first")


def test_the_reason_is_kept_with_the_person(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    browser: TestClient,
    committing_db: Database,
) -> None:
    sent: Sent = signable_envelope(owner, run, detect, company, settings=NO_CODE)
    signer = _ready(browser, sent)
    _decline(browser, signer, "Wrong company name")

    with committing_db.unit_of_work() as uow:
        row = uow.session.execute(
            text(
                "SELECT decline_reason, declined_at IS NOT NULL AS dated FROM envelope_recipients "
                "WHERE id = :r"
            ),
            {"r": signer},
        ).one()
    assert (row.decline_reason, row.dated) == ("Wrong company name", True)
