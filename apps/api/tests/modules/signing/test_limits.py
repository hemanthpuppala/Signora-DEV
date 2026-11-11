"""Limits on the signer's routes (Phase 8 LLD §13): a guess at links or codes from one address,
or a flood of saves from one session, is refused with when to try again."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.modules.identity_access.conftest import Account
from tests.modules.signing.conftest import sent_envelope
from tests.modules.signing.test_open import SIGN, open_link, token_for


def test_opening_links_is_limited_per_address(make_client: Callable[..., TestClient]) -> None:
    with make_client() as browser:
        answers = [open_link(browser, f"not-a-token-{n}").status_code for n in range(21)]

        assert answers[:20] == [404] * 20
        assert answers[20] == 429
        refused = open_link(browser, "one-more")
        assert refused.json()["code"] == "rate-limited"
        assert 0 < int(refused.headers["Retry-After"]) <= 60


def test_trying_codes_is_limited_per_address(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    make_client: Callable[..., TestClient],
) -> None:
    signer = str(sent_envelope(owner, run, detect, company).recipient("signer")["id"])
    with make_client() as browser:
        open_link(browser, token_for(signer))
        browser.post(f"{SIGN}/{signer}/code", json={})
        answers = [
            browser.post(f"{SIGN}/{signer}/verify", json={"code": "000000"}).status_code
            for _ in range(11)
        ]

    assert 429 not in answers[:10]
    assert answers[10] == 429
