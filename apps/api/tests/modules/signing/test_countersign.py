"""The countersigners' turn (Phase 8 LLD §7): after the last signer, signed in to Signora, the same
signing as a signer's; their inbox and its count; their signature saved for next time."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.blobstore import LocalBlobStore
from signora.kernel.config import Settings
from signora.kernel.db import Database
from tests.modules.documents.conftest import csrf_headers
from tests.modules.envelopes.test_send import SETTINGS, _without_signers, send
from tests.modules.identity_access.conftest import Account, idempotency_key
from tests.modules.signing.conftest import Sent, run_completion, signable_envelope
from tests.modules.signing.test_consent import NO_CODE
from tests.modules.signing.test_document import _ready
from tests.modules.signing.test_open import SIGN
from tests.modules.signing.test_signatures import STROKE
from tests.modules.signing.test_submit import _fill, _submit

ME = "/api/v1/me/countersign"


@pytest.fixture
def browser(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


@pytest.fixture
def sent(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> Sent:
    """Countersigned by ``company``: the account ``owner`` is signed in as."""
    return signable_envelope(owner, run, detect, company, settings=NO_CODE)


def _signers_done(browser: TestClient, sent: Sent) -> None:
    signer = _ready(browser, sent)
    _fill(browser, signer)
    assert _submit(browser, signer).status_code == 200


def _as(owner: TestClient, method: str, path: str, **kwargs: Any) -> Any:
    headers = {**csrf_headers(owner), **kwargs.pop("headers", {})}
    return owner.request(method, path, headers=headers, **kwargs)


def test_it_is_not_their_turn_until_every_signer_has_signed(
    sent: Sent, owner: TestClient, browser: TestClient, company: Account, committing_db: Database
) -> None:
    firm = str(sent.recipient("countersigner")["id"])

    early = owner.get(f"{SIGN}/{firm}")
    assert (early.status_code, early.json()["code"]) == (409, "not-their-turn")
    assert owner.get(f"{ME}/count").json() == {"count": 0}

    _signers_done(browser, sent)

    assert owner.get(f"{ME}/count").json() == {"count": 1}
    (waiting,) = owner.get(ME).json()["items"]
    assert (waiting["recipient_id"], waiting["signers"]) == (firm, ["Maya Chen"])
    assert waiting["signed_at"] is not None
    with committing_db.unit_of_work() as uow:
        mail = uow.session.execute(
            text(
                "SELECT category, text_body FROM email_messages WHERE to_address = :to "
                "AND category IN ('countersign_request', 'signers_signed') "
                "AND (text_body LIKE :page OR category = 'signers_signed') ORDER BY category"
            ),
            {"to": company.email, "page": f"%/countersign/{firm}%"},
        ).all()
    assert {row.category for row in mail} == {"countersign_request", "signers_signed"}


def test_a_countersigner_signs_signed_in_sees_every_value_and_keeps_their_signature(
    sent: Sent, owner: TestClient, browser: TestClient, company: Account, committing_db: Database
) -> None:
    _signers_done(browser, sent)
    firm = str(sent.recipient("countersigner")["id"])

    state = owner.get(f"{SIGN}/{firm}").json()
    assert state["next"] == "consent"  # their sign-in is the proof: no email code
    code = _as(owner, "POST", f"{SIGN}/{firm}/code", json={})
    assert code.json()["code"] == "code-not-required"
    consent = _as(
        owner, "POST", f"{SIGN}/{firm}/consent", json={"disclosure_version": "esign-disclosure-v1"}
    )
    assert consent.json()["next"] == "sign"

    fields = {f["label"]: f for f in owner.get(f"{SIGN}/{firm}/document").json()["fields"]}
    assert (
        fields["Client tax number"]["value"] == "12-3456789"
    )  # private from signers, not the firm
    assert fields["Firm signature"]["mine"] is True
    assert (
        _as(
            owner,
            "PUT",
            f"{SIGN}/{firm}/signature/signature",
            json={"method": "drawn", "strokes": STROKE},
        ).status_code
        == 200
    )
    assert _as(owner, "POST", f"{SIGN}/{firm}/apply-all/signature").json()["placed"] == 1

    done = _as(owner, "POST", f"{SIGN}/{firm}/submit", headers=idempotency_key())

    assert done.status_code == 200, done.text
    assert owner.get(f"{ME}/count").json() == {"count": 0}
    assert owner.get(ME).json()["items"] == []  # no longer waiting
    record = owner.get(ME, params={"state": "done"}).json()
    (countersigned,) = record["items"]  # but in their record
    assert countersigned["recipient_id"] == firm and countersigned["countersigned_at"]
    assert (record["total"], record["waiting"], record["done"]) == (1, 0, 1)
    found = owner.get(ME, params={"state": "done", "q": "maya"}).json()  # a signer's name, any case
    assert found["total"] == 1
    # The departments they countersign in, and a filter by one of them.
    (department,) = record["departments"]
    assert department["id"] == sent.doc.department_id
    mine = owner.get(ME, params={"state": "done", "department": department["id"]}).json()
    assert (mine["total"], mine["done"]) == (1, 1)
    other = owner.get(ME, params={"state": "done", "department": str(uuid.uuid4())}).json()
    assert (other["total"], other["waiting"], other["done"]) == (0, 0, 0)
    typo = owner.get(ME, params={"state": "done", "q": "mya chen"}).json()  # a typo
    assert [item["recipient_id"] for item in typo["items"]] == [firm]
    assert owner.get(ME, params={"state": "done", "q": "100%_nothing"}).json()["total"] == 0
    with committing_db.unit_of_work() as uow:
        kept = uow.session.execute(
            text("SELECT kind FROM saved_signatures WHERE user_id = :u"), {"u": company.user_id}
        ).scalars()
        verified = uow.session.execute(
            text(
                "SELECT data ->> 'verified_by' FROM audit_events WHERE subject_id = :e "
                "AND action = 'signing.signed' AND actor_id = :r"
            ),
            {"e": sent.id, "r": firm},
        ).scalar_one()
    assert list(kept) == ["signature"]
    assert verified == "signora_sign_in"


def test_a_countersigner_must_be_signed_in_and_send_the_csrf_token(
    sent: Sent, owner: TestClient, browser: TestClient
) -> None:
    _signers_done(browser, sent)
    firm = str(sent.recipient("countersigner")["id"])

    assert browser.get(f"{SIGN}/{firm}").status_code == 401  # the signer's browser, not signed in
    forged = owner.post(
        f"{SIGN}/{firm}/consent", json={"disclosure_version": "esign-disclosure-v1"}
    )
    assert forged.status_code == 403  # no CSRF token


def test_with_no_signer_the_countersigners_sign_at_once_and_the_envelope_completes(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
    settings: Settings,
) -> None:
    """Every signer has signed holds from the start when there is none: the countersigners' turn
    begins at send, and their signature completes the envelope."""
    doc, party = _without_signers(owner, run, detect, firm=True)
    assert party is not None
    sent = send(
        owner,
        doc,
        {
            "version_id": doc.version_id,
            "signers": [],
            "countersigners": [{"party_id": party["id"], "user_id": str(company.user_id)}],
            "settings": SETTINGS,
        },
    )
    assert sent.status_code == 201, sent.text
    envelope_id = sent.json()["id"]
    assert sent.json()["status"] == "signed"
    (firm,) = (r["id"] for r in sent.json()["recipients"])

    assert owner.get(f"{SIGN}/{firm}").json()["next"] == "consent"
    assert owner.get(f"{ME}/count").json() == {"count": 1}
    _as(owner, "POST", f"{SIGN}/{firm}/consent", json={"disclosure_version": "esign-disclosure-v1"})
    _as(
        owner,
        "PUT",
        f"{SIGN}/{firm}/signature/signature",
        json={"method": "drawn", "strokes": STROKE},
    )
    _as(owner, "POST", f"{SIGN}/{firm}/apply-all/signature")
    done = _as(owner, "POST", f"{SIGN}/{firm}/submit", headers=idempotency_key())
    assert done.status_code == 200, done.text

    run_completion(committing_db, envelope_id, LocalBlobStore(settings.blob_store.dir))
    assert owner.get(f"/api/v1/envelopes/{envelope_id}").json()["status"] == "completed"
