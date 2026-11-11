"""Limits on the signer's routes (Phase 8 LLD §13): a guess at links or codes from one address,
or a flood of saves from one person, is refused with when to try again."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient

from signora.modules.signing.limits import LIMITS
from tests.modules.identity_access.conftest import Account, idempotency_key
from tests.modules.signing.conftest import sent_envelope, signable_envelope
from tests.modules.signing.test_consent import NO_CODE
from tests.modules.signing.test_document import _ready
from tests.modules.signing.test_open import SIGN, open_link, token_for
from tests.modules.signing.test_submit import _fill, _submit


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


def test_a_persons_allowance_is_spent_only_by_their_own_checked_requests(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    make_client: Callable[..., TestClient],
) -> None:
    """Someone who knows a signer's id but holds no session for them is refused, and their refusals
    count against nobody: the signer still saves and submits."""
    sent = signable_envelope(owner, run, detect, company, settings=NO_CODE)
    with make_client() as outsider:
        for _ in range(LIMITS["act"] + 1):
            refused = outsider.post(
                f"{SIGN}/{sent.recipient('signer')['id']}/submit", headers=idempotency_key()
            )
            assert refused.status_code == 401
        field = str(uuid.uuid4())
        for _ in range(LIMITS["draft"] + 1):
            assert (
                outsider.delete(
                    f"{SIGN}/{sent.recipient('signer')['id']}/drafts/{field}"
                ).status_code
                == 401
            )

    with make_client() as browser:
        signer = _ready(browser, sent)
        _fill(browser, signer)
        done = _submit(browser, signer)
    assert done.status_code == 200, done.text
