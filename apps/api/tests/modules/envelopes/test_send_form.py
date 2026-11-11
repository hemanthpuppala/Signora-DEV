"""The send form, generated from an approved version (Phase 7 LLD §2, §10, §11.1)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.modules.documents.conftest import csrf_headers, log_in
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
    from_client = {
        f["id"]: f["from_recipient"] for f in form["fields"] if f["party_id"] == client["id"]
    }
    for f in doc.view["fields"]:  # the signer's own details are theirs, never asked (7b)
        if f["party_id"] == client["id"] and f["holds"] == "email":
            assert from_client[f["id"]] == "email"
        if f["party_id"] == client["id"] and f["holds"] in ("full_name", "first_name", "last_name"):
            assert from_client[f["id"]] == "name"
    assert "email" in from_client.values()
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
    assert form["pages"] and form["pages"][0]["width"] > 0  # for drawing the values
    effective = by_id[doc.field("Effective date")["id"]]
    assert effective["places"] == [
        # the agreement's text beside it, measured when the version was approved (7b)
        {"page": 1, "rect": [300.0, 40.0, 400.0, 60.0], "option_value": None, "text_size": 10.0}
    ]


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


def test_the_form_carries_who_may_countersign_for_anyone_who_may_send(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    make_client: Callable[..., TestClient],
    add_member: Callable[..., Account],
) -> None:
    """The send's countersigner list came from the members directory, which needs a permission
    of its own. Someone who may send through a grant in one department does not hold it: their
    list was empty, and on a template with a countersigner and no default they could not send.
    Whoever may send is given who may countersign with the form (any active member, Phase 3
    §4.2)."""
    doc = sendable(owner, run, detect)
    granted = add_member(company, role="read")
    gone = add_member(company, role="read")
    owner.put(
        f"/api/v1/departments/{doc.department_id}/grants",
        json={"user_ids": [str(granted.user_id)]},
        headers=csrf_headers(owner),
    ).raise_for_status()
    owner.delete(f"/api/v1/members/{gone.user_id}", headers=csrf_headers(owner)).raise_for_status()

    with make_client() as theirs:
        log_in(theirs, granted.email)
        assert theirs.get("/api/v1/members/directory").status_code == 403  # not theirs to list
        form = theirs.get(f"{DOCUMENTS}/{doc.document_id}/versions/{doc.version_id}/send-form")
        assert form.status_code == 200, form.text

    people = {c["user_id"]: (c["name"], c["email"]) for c in form.json()["colleagues"]}
    assert str(company.user_id) in people and str(granted.user_id) in people
    assert str(gone.user_id) not in people  # active members only
    assert [c["name"] for c in form.json()["colleagues"]] == sorted(n for n, _ in people.values())
