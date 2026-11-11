"""Signatures and initials (Phase 8 LLD §5): adopted once, checked, placed by a tap or by Apply to
all, changed in every place at once, fingerprinted."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from signora.modules.signing.signatures import fingerprint
from tests.modules.identity_access.conftest import Account
from tests.modules.signing.conftest import Sent, signable_envelope
from tests.modules.signing.test_consent import NO_CODE
from tests.modules.signing.test_document import _fields, _ready
from tests.modules.signing.test_open import SIGN

STROKE = [[(100, 200), (300, 150), (500, 260), (700, 180)]]


@pytest.fixture
def browser(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


@pytest.fixture
def sent(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> Sent:
    return signable_envelope(owner, run, detect, company, settings=NO_CODE)


def _adopt(browser: TestClient, signer: str, kind: str = "signature", **body: Any) -> Any:
    return browser.put(f"{SIGN}/{signer}/signature/{kind}", json=body)


def _signature_place(fields: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return next(f for f in fields.values() if f["mine"] and f["holds"] == "signature")


def test_a_drawing_is_adopted_with_its_fingerprint_and_a_scribble_is_not(
    sent: Sent, browser: TestClient
) -> None:
    signer = _ready(browser, sent)

    def why(**body: Any) -> str:
        answer = _adopt(browser, signer, **body)
        assert answer.status_code == 422, answer.text
        return str(answer.json()["errors"][0]["message"])

    assert why(method="drawn", strokes=[]) == "Draw your signature"
    assert why(method="drawn", strokes=[[(10, 10), (12, 11)]]) == "Draw your signature"  # a dot
    assert why(method="drawn", strokes=[[(10, 10), (1200, 10)]]) == "Draw inside the box"
    assert why(method="typed", text="Maya Chen", font="liberation-sans") == "Choose a style"
    assert why(method="typed", text="   ", font="liberation-sans") == "Type your name"

    adopted = _adopt(browser, signer, method="drawn", strokes=STROKE)
    assert adopted.status_code == 200, adopted.text
    body = adopted.json()
    expected = fingerprint("signature", "drawn", None, None, [[list(p) for p in s] for s in STROKE])
    assert body["signature_id"] == expected.hex()[:16]
    state = browser.get(f"{SIGN}/{signer}/signature").json()
    assert [a["kind"] for a in state["adopted"]] == ["signature"]


def test_a_place_is_signed_by_a_tap_once_a_signature_is_adopted(
    sent: Sent, browser: TestClient
) -> None:
    signer = _ready(browser, sent)
    place = _signature_place(_fields(browser, signer))
    tap = f"{SIGN}/{signer}/drafts/{place['id']}"

    early = browser.put(tap, json={"value": "signed"})
    assert (early.status_code, early.json()["code"]) == (409, "adopt-first")
    assert _adopt(browser, signer, method="drawn", strokes=STROKE).status_code == 200
    assert browser.put(tap, json={"value": "Maya"}).status_code == 422
    signed = browser.put(tap, json={"value": "signed"})
    assert (signed.status_code, signed.json()["value"]) == (200, "signed")
    assert _signature_place(_fields(browser, signer))["draft"] == "signed"

    assert browser.delete(tap).status_code == 204  # unsign it
    assert _signature_place(_fields(browser, signer))["draft"] is None


def test_apply_to_all_signs_every_place_of_the_kind(sent: Sent, browser: TestClient) -> None:
    signer = _ready(browser, sent)

    early = browser.post(f"{SIGN}/{signer}/apply-all/signature")
    assert (early.status_code, early.json()["code"]) == (409, "adopt-first")
    _adopt(browser, signer, method="drawn", strokes=STROKE)

    placed = browser.post(f"{SIGN}/{signer}/apply-all/signature")

    assert placed.status_code == 200, placed.text
    mine = [f for f in _fields(browser, signer).values() if f["mine"] and f["holds"] == "signature"]
    assert placed.json()["placed"] == len(mine) >= 1
    assert all(f["draft"] == "signed" for f in mine)


def test_a_changed_signature_is_the_one_every_signed_place_shows(
    sent: Sent, browser: TestClient
) -> None:
    signer = _ready(browser, sent)
    first = _adopt(browser, signer, method="drawn", strokes=STROKE).json()["signature_id"]
    browser.post(f"{SIGN}/{signer}/apply-all/signature")

    second = _adopt(browser, signer, method="drawn", strokes=[[(50, 50), (950, 350)]]).json()

    assert second["signature_id"] != first
    state = browser.get(f"{SIGN}/{signer}/signature").json()
    assert [a["signature_id"] for a in state["adopted"]] == [second["signature_id"]]
    assert _signature_place(_fields(browser, signer))["draft"] == "signed"  # still signed, with it


def test_the_fingerprint_is_of_what_was_adopted_and_nothing_else() -> None:
    one = fingerprint("signature", "typed", "Maya Chen", "font-a", None)

    assert one == fingerprint("signature", "typed", "Maya Chen", "font-a", None)
    assert one != fingerprint("initials", "typed", "Maya Chen", "font-a", None)
    assert one != fingerprint("signature", "typed", "Maya  Chen", "font-a", None)
    assert len(one) == 32
