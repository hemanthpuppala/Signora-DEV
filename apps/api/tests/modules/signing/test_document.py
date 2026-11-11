"""The signer's document and drafts (Phase 8 LLD §4): what each person may see, values checked as
they are saved by the send's rules, drafts that only their person sees, and "viewed" once."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.modules.identity_access.conftest import Account
from tests.modules.signing.conftest import Sent, signable_envelope
from tests.modules.signing.test_consent import NO_CODE, _consent
from tests.modules.signing.test_open import ENVELOPES, SIGN, open_link, token_for


@pytest.fixture
def browser(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


@pytest.fixture
def sent(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> Sent:
    return signable_envelope(owner, run, detect, company, settings=NO_CODE)


def _ready(browser: TestClient, sent: Sent) -> str:
    signer = str(sent.recipient("signer")["id"])
    open_link(browser, token_for(signer))
    assert _consent(browser, signer).status_code == 200
    return signer


def _fields(browser: TestClient, signer: str) -> dict[str, dict[str, Any]]:
    answer = browser.get(f"{SIGN}/{signer}/document")
    assert answer.status_code == 200, answer.text
    return {field["label"]: field for field in answer.json()["fields"]}


def _save(browser: TestClient, signer: str, field: dict[str, Any], value: str) -> Any:
    return browser.put(f"{SIGN}/{signer}/drafts/{field['id']}", json={"value": value})


def test_the_document_waits_for_consent(sent: Sent, browser: TestClient) -> None:
    signer = str(sent.recipient("signer")["id"])
    open_link(browser, token_for(signer))

    for path in ("document", "pdf"):
        refused = browser.get(f"{SIGN}/{signer}/{path}")
        assert (refused.status_code, refused.json()["code"]) == (403, "consent-first")


def test_each_field_shows_what_this_person_may_see(sent: Sent, browser: TestClient) -> None:
    signer = _ready(browser, sent)

    fields = _fields(browser, signer)
    document = browser.get(f"{SIGN}/{signer}/document").json()

    name, email = fields["Client printed name"], fields["Client email"]
    assert (name["mine"], name["locked"], name["value"]) == (True, True, "Maya Chen")
    assert (email["mine"], email["locked"]) == (True, True)  # the address it was sent to
    assert email["value"] == sent.recipient("signer")["email"]
    title = fields["Client title"]
    assert (title["mine"], title["required"], title["locked"], title["value"]) == (
        True,
        True,
        False,
        None,
    )
    assert fields["Client phone"]["required"] is False
    effective = fields["Effective date"]  # the sender's: shown, not theirs
    assert (effective["mine"], effective["value"]) == (False, "2026-12-01")
    firm = fields["Firm signature"]
    assert (firm["mine"], firm["hidden"], firm["value"]) == (False, "countersigner", None)
    assert [(p["label"], p["kind"]) for p in document["parties"]] == [
        ("Client", "signer"),
        ("Firm", "countersigner"),
    ]
    assert document["pages"] and document["font"]["id"] == "liberation-sans"

    pdf = browser.get(f"{SIGN}/{signer}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["cache-control"] == "no-store"


def test_a_draft_is_checked_like_any_value_and_kept_for_its_person(
    sent: Sent, browser: TestClient, owner: TestClient
) -> None:
    signer = _ready(browser, sent)
    fields = _fields(browser, signer)

    saved = _save(browser, signer, fields["Client phone"], "(415) 555-0100")
    assert saved.status_code == 200, saved.text
    bad = _save(browser, signer, fields["Client phone"], "call me")
    assert bad.status_code == 422
    long = _save(browser, signer, fields["Client title"], "Chief " * 60)
    assert (long.status_code, long.json()["errors"][0]["message"]) == (422, "Too long for its box")
    assert _save(browser, signer, fields["Client title"], "Founder").status_code == 200

    again = _fields(browser, signer)
    assert again["Client title"]["draft"] == "Founder"
    assert again["Client phone"]["draft"] is not None
    sender_view = owner.get(f"{ENVELOPES}/{sent.id}").json()  # drafts are not values yet
    assert {v["field_id"] for v in sender_view["values"]}.isdisjoint(
        {fields["Client title"]["id"], fields["Client phone"]["id"]}
    )

    assert (
        browser.delete(f"{SIGN}/{signer}/drafts/{fields['Client title']['id']}").status_code == 204
    )
    assert _fields(browser, signer)["Client title"]["draft"] is None


def test_a_field_not_theirs_locked_or_not_asked_is_refused(sent: Sent, browser: TestClient) -> None:
    signer = _ready(browser, sent)
    fields = _fields(browser, signer)

    def code(field: str, value: str) -> str:
        return str(_save(browser, signer, fields[field], value).json()["code"])

    assert code("Effective date", "2026-12-02") == "not-yours"
    assert code("Client printed name", "Someone Else") == "field-locked"
    assert code("Client email", "other@example.com") == "field-locked"
    assert code("Marketing topics", "Events") == "field-not-asked"


def test_a_draft_goes_with_the_answer_that_asked_for_it(sent: Sent, browser: TestClient) -> None:
    signer = _ready(browser, sent)
    fields = _fields(browser, signer)
    box, follow = fields["Client marketing"], fields["Marketing topics"]

    assert _save(browser, signer, box, "true").status_code == 200
    stored = _save(browser, signer, follow, "  Events  ")
    assert (stored.status_code, stored.json()["value"]) == (200, "Events")  # as stored

    assert _save(browser, signer, box, "false").status_code == 200  # no longer asks for it
    assert _fields(browser, signer)["Marketing topics"]["draft"] is None


def test_a_private_value_is_seen_by_the_person_who_gives_it(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    make_client: Callable[..., TestClient],
) -> None:
    sent = signable_envelope(owner, run, detect, company, settings=NO_CODE)
    signer = str(sent.recipient("signer")["id"])
    with make_client() as browser:
        open_link(browser, token_for(signer))
        _consent(browser, signer)
        tax = _fields(browser, signer)["Client tax number"]
        assert _save(browser, signer, tax, "12-3456789").status_code == 200
        assert _fields(browser, signer)["Client tax number"]["draft"] == "12-3456789"  # their own


def test_viewed_is_recorded_once(sent: Sent, browser: TestClient, owner: TestClient) -> None:
    signer = _ready(browser, sent)

    assert browser.post(f"{SIGN}/{signer}/viewed").status_code == 204
    assert browser.post(f"{SIGN}/{signer}/viewed").status_code == 204

    envelope = owner.get(f"{ENVELOPES}/{sent.id}").json()
    assert envelope["status"] == "viewed"
    assert envelope["recipients"][0]["status"] == "viewed"
    assert [entry["action"] for entry in envelope["timeline"]].count("signing.viewed") <= 1
