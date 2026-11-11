"""The email code (Phase 8 LLD §2): sent when asked, kept while live, six digits, single use, ten
minutes, five wrong tries, a minute between codes and five an hour; verified per browser."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.documents.conftest import csrf_headers
from tests.modules.identity_access.conftest import Account
from tests.modules.signing.conftest import Sent, sent_envelope
from tests.modules.signing.test_open import SIGN, open_link, token_for


@pytest.fixture
def browser(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


@pytest.fixture
def sent(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> Sent:
    return sent_envelope(owner, run, detect, company)


def _opened(browser: TestClient, sent: Sent) -> str:
    signer = str(sent.recipient("signer")["id"])
    assert open_link(browser, token_for(signer)).status_code == 200
    return signer


def _codes(db: Database, recipient_id: str) -> list[str]:
    """The codes emailed to this person, oldest first."""
    with db.unit_of_work() as uow:
        subjects = uow.session.execute(
            text(
                "SELECT e.subject FROM email_messages e JOIN envelope_recipients r "
                "ON r.email = e.to_address WHERE r.id = :r AND e.category = 'sign_code' "
                "ORDER BY e.created_at"
            ),
            {"r": recipient_id},
        ).scalars()
        return [
            subject[:6] for subject in subjects if re.match(r"\d{6} is your code for ", subject)
        ]


def _age_code(db: Database, recipient_id: str, interval: str) -> None:
    """Move the code's clock back, as if ``interval`` had passed."""
    with db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "UPDATE signing_codes SET sent_at = sent_at - CAST(:i AS interval), "
                "expires_at = expires_at - CAST(:i AS interval), "
                "window_start = window_start - CAST(:i AS interval) WHERE recipient_id = :r"
            ),
            {"i": interval, "r": recipient_id},
        )


def _code(browser: TestClient, recipient_id: str, **body: Any) -> Any:
    return browser.post(f"{SIGN}/{recipient_id}/code", json=body)


def _verify(browser: TestClient, recipient_id: str, code: str) -> Any:
    return browser.post(f"{SIGN}/{recipient_id}/verify", json={"code": code})


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def test_a_code_is_sent_kept_while_live_and_verifies_once(
    sent: Sent, browser: TestClient, committing_db: Database
) -> None:
    signer = _opened(browser, sent)

    first = _code(browser, signer)
    assert first.status_code == 200, first.text
    assert first.json()["email_masked"].startswith("m•••@")
    assert first.json()["resend_after"] == 60
    again = _code(browser, signer)  # a reload: the live code is kept, nothing is sent
    assert again.json()["sent_at"] == first.json()["sent_at"]
    (code,) = _codes(committing_db, signer)

    wrong = _verify(browser, signer, _wrong(code))
    assert wrong.status_code == 422
    assert wrong.json()["errors"][0]["message"] == "That code isn't right. 4 tries left."
    with committing_db.unit_of_work() as uow:  # the wrong try was kept despite the refusal
        assert (
            uow.session.execute(
                text("SELECT wrong_tries FROM signing_codes WHERE recipient_id = :r"), {"r": signer}
            ).scalar_one()
            == 1
        )

    right = _verify(browser, signer, code)
    assert right.status_code == 200, right.text
    assert right.json()["next"] == "consent"
    assert browser.get(f"{SIGN}/{signer}").json()["next"] == "consent"
    assert _verify(browser, signer, code).json()["code"] == "code-ended"  # single use

    with committing_db.unit_of_work() as uow:
        actions = uow.session.execute(
            text(
                "SELECT action FROM audit_events WHERE subject_id = :e "
                "AND action LIKE 'signing.%' ORDER BY seq"
            ),
            {"e": sent.id},
        ).scalars()
        assert list(actions) == [
            "signing.opened",
            "signing.code_sent",
            "signing.code_wrong",
            "signing.verified",
        ]


def test_a_new_code_waits_a_minute_and_ends_the_old_one(
    sent: Sent, browser: TestClient, committing_db: Database
) -> None:
    signer = _opened(browser, sent)
    assert _code(browser, signer).status_code == 200

    soon = _code(browser, signer, again=True)
    assert (soon.status_code, soon.json()["code"]) == (429, "code-wait")
    assert 0 < int(soon.headers["Retry-After"]) <= 60

    _age_code(committing_db, signer, "61 seconds")
    assert _code(browser, signer, again=True).status_code == 200
    old, new = _codes(committing_db, signer)
    if old != new:  # one in a million, two codes are the same digits
        assert _verify(browser, signer, old).status_code == 422
    assert _verify(browser, signer, new).status_code == 200


def test_five_wrong_tries_end_the_code(
    sent: Sent, browser: TestClient, committing_db: Database
) -> None:
    signer = _opened(browser, sent)
    _code(browser, signer)
    (code,) = _codes(committing_db, signer)

    answers = [_verify(browser, signer, _wrong(code)) for _ in range(5)]

    assert [a.json()["errors"][0]["message"] for a in answers][-2:] == [
        "That code isn't right. 1 try left.",
        "That code isn't right. Ask for a new code.",
    ]
    ended = _verify(browser, signer, code)
    assert (ended.status_code, ended.json()["code"]) == (410, "code-ended")


def test_a_code_ends_after_ten_minutes(
    sent: Sent, browser: TestClient, committing_db: Database
) -> None:
    signer = _opened(browser, sent)
    _code(browser, signer)
    (code,) = _codes(committing_db, signer)
    _age_code(committing_db, signer, "11 minutes")

    assert _verify(browser, signer, code).status_code == 410
    assert _code(browser, signer).status_code == 200  # an ended code is replaced when asked


def test_five_codes_an_hour(sent: Sent, browser: TestClient, committing_db: Database) -> None:
    signer = _opened(browser, sent)
    for _ in range(5):
        assert _code(browser, signer, again=True).status_code == 200
        with committing_db.unit_of_work() as uow:  # a minute passes, inside the same hour
            uow.session.execute(
                text(
                    "UPDATE signing_codes SET sent_at = sent_at - interval '61 seconds' "
                    "WHERE recipient_id = :r"
                ),
                {"r": signer},
            )

    sixth = _code(browser, signer, again=True)
    assert (sixth.status_code, sixth.json()["code"]) == (429, "code-limit")
    assert int(sixth.headers["Retry-After"]) > 60

    _age_code(committing_db, signer, "1 hour")
    assert _code(browser, signer, again=True).status_code == 200


def test_verification_belongs_to_one_browser(
    sent: Sent, browser: TestClient, committing_db: Database, make_client: Callable[..., TestClient]
) -> None:
    signer = _opened(browser, sent)
    _code(browser, signer)
    (code,) = _codes(committing_db, signer)
    assert _verify(browser, signer, code).status_code == 200

    with make_client() as phone:
        assert open_link(phone, token_for(signer)).json()["next"] == "verify"
        assert phone.get(f"{SIGN}/{signer}").json()["next"] == "verify"


def test_a_corrected_email_ends_the_code(
    sent: Sent, browser: TestClient, owner: TestClient, committing_db: Database
) -> None:
    signer = _opened(browser, sent)
    _code(browser, signer)
    (code,) = _codes(committing_db, signer)
    corrected = owner.patch(
        f"/api/v1/envelopes/{sent.id}/recipients/{signer}",
        json={"email": f"maya-{uuid.uuid4().hex[:8]}@example.org"},
        headers=csrf_headers(owner),
    )
    assert corrected.status_code == 200, corrected.text
    assert open_link(browser, token_for(signer, version=2)).json()["next"] == "verify"

    assert _verify(browser, signer, code).status_code == 410


def test_no_code_when_the_envelope_asks_for_none(
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
    signer = _opened(browser, sent_envelope(owner, run, detect, company, settings=settings))

    refused = _code(browser, signer)
    assert (refused.status_code, refused.json()["code"]) == (409, "code-not-required")
