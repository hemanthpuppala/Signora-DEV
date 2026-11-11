"""Submit (Phase 8 LLD §6): checked again on the server, written once, the countersigners' turn
begun when the last signer signs."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.documents.conftest import csrf_headers
from tests.modules.identity_access.conftest import Account, idempotency_key
from tests.modules.signing.conftest import Sent, signable_envelope
from tests.modules.signing.test_consent import NO_CODE
from tests.modules.signing.test_document import _fields, _ready, _save
from tests.modules.signing.test_open import ENVELOPES, SIGN
from tests.modules.signing.test_signatures import STROKE, _adopt


@pytest.fixture
def browser(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


@pytest.fixture
def sent(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> Sent:
    return signable_envelope(owner, run, detect, company, settings=NO_CODE)


def _submit(browser: TestClient, signer: str, key: dict[str, str] | None = None) -> Any:
    return browser.post(f"{SIGN}/{signer}/submit", headers=key or idempotency_key())


def _fill(browser: TestClient, signer: str) -> dict[str, dict[str, Any]]:
    fields = _fields(browser, signer)
    assert _save(browser, signer, fields["Client title"], "Founder").status_code == 200
    assert _save(browser, signer, fields["Client tax number"], "12-3456789").status_code == 200
    assert _adopt(browser, signer, method="drawn", strokes=STROKE).status_code == 200
    assert browser.post(f"{SIGN}/{signer}/apply-all/signature").status_code == 200
    return fields


def test_each_field_that_needs_attention_is_named_and_nothing_is_written(
    sent: Sent, browser: TestClient, owner: TestClient
) -> None:
    signer = _ready(browser, sent)
    fields = _fields(browser, signer)

    refused = _submit(browser, signer)

    assert refused.status_code == 422
    named = {error["field"]: error["message"] for error in refused.json()["errors"]}
    assert named[fields["Client title"]["id"]] == "Fill this in"
    assert named[fields["Client tax number"]["id"]] == "Fill this in"
    signature = next(f for f in fields.values() if f["mine"] and f["holds"] == "signature")
    assert named[signature["id"]] == "Sign here"
    assert fields["Client phone"]["id"] not in named  # optional
    assert owner.get(f"{ENVELOPES}/{sent.id}").json()["recipients"][0]["status"] != "signed"


def test_a_submit_writes_the_values_once_and_begins_the_countersigners_turn(
    sent: Sent, browser: TestClient, owner: TestClient, committing_db: Database
) -> None:
    signer = _ready(browser, sent)
    fields = _fill(browser, signer)
    key = idempotency_key()

    done = _submit(browser, signer, key)

    assert done.status_code == 200, done.text
    signed_at = done.json()["signed_at"]
    assert _submit(browser, signer, key).json() == done.json()  # the same key: the stored answer
    assert _submit(browser, signer).json()["signed_at"] == signed_at  # a new key: still once

    envelope = owner.get(f"{ENVELOPES}/{sent.id}").json()
    assert envelope["status"] == "signed"
    by_kind = {r["kind"]: r for r in envelope["recipients"]}
    assert by_kind["signer"]["status"] == "signed"
    assert by_kind["countersigner"]["status"] == "sent"  # their turn
    values = {v["field_id"]: v["value"] for v in envelope["values"]}
    assert values[fields["Client title"]["id"]] == "Founder"
    assert values[fields["Client printed name"]["id"]] == "Maya Chen"  # the name they signed as
    signature = next(f for f in fields.values() if f["mine"] and f["holds"] == "signature")
    assert values[signature["id"]].startswith("signature:")
    assert fields["Client phone"]["id"] not in values

    with committing_db.unit_of_work() as uow:
        left = uow.session.execute(
            text("SELECT count(*) FROM signing_drafts WHERE recipient_id = :r"), {"r": signer}
        ).scalar_one()
        data = uow.session.execute(
            text(
                "SELECT data FROM audit_events WHERE subject_id = :e AND action = 'signing.signed'"
            ),
            {"e": sent.id},
        ).scalar_one()
    assert left == 0
    assert data["verified_by"] == "email_link" and len(data["values_sha256"]) == 64

    late = _save(browser, signer, fields["Client phone"], "4155550100")
    assert (late.status_code, late.json()["code"]) == (409, "already-signed")


def test_a_closed_envelope_takes_no_submit(
    sent: Sent, browser: TestClient, owner: TestClient
) -> None:
    signer = _ready(browser, sent)
    _fill(browser, signer)
    assert (
        owner.post(f"{ENVELOPES}/{sent.id}/cancel", headers=csrf_headers(owner)).status_code == 200
    )

    closed = _submit(browser, signer)

    assert (closed.status_code, closed.json()["code"]) == (404, "link-closed")
