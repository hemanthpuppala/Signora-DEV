"""The send form, generated from an approved version (Phase 7 LLD §2, §10, §11.1)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.modules.documents.conftest import log_in
from tests.modules.envelopes.conftest import make_countersigner, sendable
from tests.modules.identity_access.conftest import Account
from tests.modules.review.test_save import DOCUMENTS, _in_review


def test_only_an_approved_version_can_be_sent(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    document_id, version_id = _in_review(owner, run, detect)

    refused = owner.get(f"{DOCUMENTS}/{document_id}/versions/{version_id}/send-form")

    assert (refused.status_code, refused.json()["code"]) == (409, "version-not-approved")


def test_the_form_asks_what_the_document_needs(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
) -> None:
    doc = sendable(owner, run, detect)
    make_countersigner(owner, doc.department_id, [str(company.user_id)])

    form = owner.get(f"{DOCUMENTS}/{doc.document_id}/versions/{doc.version_id}/send-form").json()

    client, firm = doc.party("Client"), doc.party("Firm")
    assert [s["party_id"] for s in form["signers"]] == [client["id"]]
    assert form["signers"][0]["email_field_ids"] == [
        f["id"]
        for f in doc.view["fields"]
        if f["party_id"] == client["id"] and f["holds"] == "email"
    ]
    (countersigner,) = form["countersigners"]
    assert countersigner["party_id"] == firm["id"]
    assert countersigner["default"]["user_id"] == str(company.user_id)  # the department's first
    by_id = {f["id"]: f for f in form["fields"]}
    signing = {
        f["id"]
        for f in doc.view["fields"]
        if f["holds"] in ("signature", "initials", "date_signed")
    }
    assert not signing & by_id.keys()  # given by signing, never asked here
    assert by_id[doc.field("Effective date")["id"]]["required"] is True  # only the sender can
    assert by_id[doc.field("Effective date")["id"]]["party_id"] is None
    assert by_id[doc.field("Internal note")["id"]]["required"] is False
    assert not any(f["required"] for f in form["fields"] if f["party_id"])  # a party's: optional
    assert form["settings"] == {
        "require_email_code": True,
        "reminder_interval_hours": 24,
        "max_reminders": 5,
        "expiry_days": 14,
        "notify_emails": [],
    }
    document = owner.get(f"{DOCUMENTS}/{doc.document_id}").json()
    assert (form["document_name"], form["version_number"]) == (document["name"], 1)


def test_a_countersigner_party_beyond_the_departments_list_is_left_to_choose(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    doc = sendable(owner, run, detect)  # the department has no countersigners

    form = owner.get(f"{DOCUMENTS}/{doc.document_id}/versions/{doc.version_id}/send-form").json()

    assert form["countersigners"][0]["default"] is None


def test_read_only_members_cannot_send(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    doc = sendable(owner, run, detect)
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        response = theirs.get(f"{DOCUMENTS}/{doc.document_id}/versions/{doc.version_id}/send-form")
    assert response.status_code == 403
