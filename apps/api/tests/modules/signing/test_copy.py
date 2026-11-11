"""The done screen and the copy as signed so far (Phase 8 LLD §9, §10): what is next, and a PDF of
the original's pages with this person's view of the values written in."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from urllib.parse import unquote

import pymupdf
import pytest
from fastapi.testclient import TestClient

from tests.modules.identity_access.conftest import Account
from tests.modules.signing.conftest import Sent, signable_envelope
from tests.modules.signing.test_consent import NO_CODE
from tests.modules.signing.test_document import _ready
from tests.modules.signing.test_open import SIGN
from tests.modules.signing.test_submit import _fill, _submit


@pytest.fixture
def browser(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


@pytest.fixture
def sent(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> Sent:
    return signable_envelope(owner, run, detect, company, settings=NO_CODE)


def test_the_done_screen_says_what_comes_next(sent: Sent, browser: TestClient) -> None:
    signer = _ready(browser, sent)
    assert browser.get(f"{SIGN}/{signer}/done").json()["code"] == "not-their-turn"  # not signed yet
    _fill(browser, signer)
    signed_at = _submit(browser, signer).json()["signed_at"]

    done = browser.get(f"{SIGN}/{signer}/done").json()

    assert done["signed_at"] == signed_at
    assert done["verified_by"] == "email_link"
    assert done["waiting_for"] == []
    assert done["countersigning"]  # the company, whose countersigner has still to sign
    assert browser.get(f"{SIGN}/{signer}").json()["next"] == "done"


def test_the_copy_is_the_document_with_what_this_person_may_see_written_in(
    sent: Sent, browser: TestClient
) -> None:
    signer = _ready(browser, sent)
    _fill(browser, signer)
    _submit(browser, signer)

    answer = browser.get(f"{SIGN}/{signer}/copy.pdf")

    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/pdf"
    disposition = answer.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "signed by Maya Chen.pdf" in unquote(disposition)
    doc = pymupdf.open(stream=answer.content, filetype="pdf")
    words = "".join(doc[i].get_text() for i in range(doc.page_count))
    assert "Founder" in words and "Maya Chen" in words and "12-3456789" in words  # their own
    assert f"Signora envelope ID: {sent.id.upper()}" in words
    assert "Signed by:" in words  # their signature, framed with its ID
    assert not doc.is_form_pdf
