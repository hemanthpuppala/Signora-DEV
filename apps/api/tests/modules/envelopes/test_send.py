"""Sending an approved version (Phase 7 LLD §2, §5, §8, §10)."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.config import get_settings
from signora.kernel.db import Database
from signora.modules.envelopes.links import link_key, read_token
from tests.modules.documents.conftest import create_department, csrf_headers, log_in, new_document
from tests.modules.envelopes.conftest import Sendable, make_countersigner, sendable
from tests.modules.identity_access.conftest import Account, idempotency_key
from tests.modules.review.test_approve import _approve
from tests.modules.review.test_save import DOCUMENTS, _body, _drawn, _in_review, _save, _view
from tests.support import forms
from tests.support.ai import FakeAssigner

SAMPLE = {
    "date": "2026-12-01",
    "number": "1",
    "currency": "1000",
    "percent": "10",
    "checkbox": "true",
}


def required_values(api: TestClient, doc: Sendable) -> list[dict[str, str]]:
    """A valid value for each field the sender must fill (the form says which)."""
    form = api.get(f"{DOCUMENTS}/{doc.document_id}/versions/{doc.version_id}/send-form").json()
    return [
        {
            "field_id": item["id"],
            "value": item["options"][0]["value"]
            if item["options"]
            else SAMPLE.get(item["holds"], "Delaware"),
        }
        for item in form["fields"]
        if item["required"]
    ]


def request_for(
    api: TestClient, doc: Sendable, colleague: Account, **override: Any
) -> dict[str, Any]:
    """A valid send of the test NDA; ``override`` replaces any part."""
    body: dict[str, Any] = {
        "version_id": doc.version_id,
        "copies": [{"name": "Records", "email": "records@firm.example"}],
        "settings": {
            "require_email_code": True,
            "reminder_interval_hours": 48,
            "max_reminders": 3,
            "expiry_days": 30,
            "notify_emails": ["Desk@Firm.example"],
        },
    }
    if "signers" not in override:
        body["signers"] = [
            {
                "party_id": doc.party("Client")["id"],
                "name": "Maya Chen",
                # Its own address: the test database keeps every earlier test's mail.
                "email": f"Maya-{uuid.uuid4().hex[:8]}@Example.com",
            }
        ]
    if "countersigners" not in override:
        body["countersigners"] = [
            {"party_id": doc.party("Firm")["id"], "user_id": str(colleague.user_id)}
        ]
    if "values" not in override:
        effective = doc.field("Effective date")["id"]
        body["values"] = [v for v in required_values(api, doc) if v["field_id"] != effective] + [
            {"field_id": effective, "value": "2026-12-01"}
        ]
    body.update(override)
    return body


def send(
    api: TestClient, doc: Sendable, body: dict[str, Any], key: dict[str, str] | None = None
) -> Any:
    return api.post(
        f"{DOCUMENTS}/{doc.document_id}/envelopes",
        json=body,
        headers={**csrf_headers(api), **(key or idempotency_key())},
    )


def test_sending_writes_the_envelope_emails_every_signer_and_waits_for_the_firm(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    doc = sendable(owner, run, detect)

    sent = send(owner, doc, request_for(owner, doc, company))

    assert sent.status_code == 201, sent.text
    envelope = sent.json()
    document = owner.get(f"{DOCUMENTS}/{doc.document_id}").json()
    assert envelope["title"] == f"{document['name']} · Maya Chen"
    assert (envelope["status"], envelope["version_number"]) == ("sent", 1)
    assert (envelope["reminder_interval_hours"], envelope["max_reminders"]) == (48, 3)
    assert envelope["notify_emails"] == ["desk@firm.example"]
    signer, firm, copy = envelope["recipients"]
    address = signer["email"]
    assert (signer["kind"], signer["status"]) == ("signer", "sent")
    assert address.startswith("maya-") and address.endswith("@example.com")  # normalised
    assert signer["party_label"] == "Client"
    assert signer["delivery"]["status"] == "queued"
    assert (firm["kind"], firm["status"], firm["email"]) == (
        "countersigner",
        "waiting",
        company.email,
    )
    assert firm["delivery"] is None  # nothing sent to the firm until every signer has signed (§3)
    assert (copy["kind"], copy["party_id"], copy["status"]) == ("copy", None, "waiting")
    values = {v["field_id"]: v["value"] for v in envelope["values"]}
    assert values[doc.field("Effective date")["id"]] == "2026-12-01"
    assert values[doc.field("Client email")["id"]] == address  # the signer's, from the send
    assert doc.field("Client printed name")["id"] not in values  # the name they sign as, later
    assert envelope["timeline"][0]["action"] == "envelope.sent"
    assert owner.get(f"/api/v1/envelopes/{envelope['id']}").json() == envelope

    with committing_db.unit_of_work() as uow:
        emails = uow.session.execute(
            text(
                "SELECT to_address, subject, text_body, reply_to, category FROM email_messages "
                "WHERE category = 'sign_request' AND to_address IN (:signer, :firm)"
            ),
            {"signer": address, "firm": company.email},
        ).all()
    (email,) = emails  # the signer only
    assert email.reply_to == company.email  # a reply reaches the sender
    assert email.subject.endswith(f"asks you to sign {document['name']}")
    token = re.search(r"/s/([A-Za-z0-9_-]+)", email.text_body)
    assert token is not None
    claim = read_token(link_key(get_settings().app.secret_key.get_secret_value()), token.group(1))
    assert claim is not None and (str(claim.recipient_id), claim.link_version) == (signer["id"], 1)
    assert "It expires on" in email.text_body


def test_a_retried_send_makes_one_envelope(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    doc = sendable(owner, run, detect)
    key = idempotency_key()

    body = request_for(owner, doc, company)
    first = send(owner, doc, body, key)
    again = send(owner, doc, body, key)  # the same request: answered with the first envelope

    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json()["id"] == first.json()["id"]
    with committing_db.unit_of_work() as uow:
        count = uow.session.execute(
            text("SELECT count(*) FROM envelopes WHERE document_id = :d"), {"d": doc.document_id}
        ).scalar_one()
    assert count == 1


def test_each_problem_is_named(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> None:
    doc = sendable(owner, run, detect)
    signature = doc.field("Firm signature")["id"]

    refused = send(
        owner,
        doc,
        request_for(
            owner,
            doc,
            company,
            signers=[
                {"party_id": doc.party("Client")["id"], "name": "Maya", "email": "not an email"}
            ],
            countersigners=[],
            values=[
                {"field_id": doc.field("Effective date")["id"], "value": "next Tuesday"},
                {"field_id": signature, "value": "R. Hale"},
                {"field_id": str(uuid.uuid4()), "value": "x"},
            ],
        ),
    )

    assert refused.status_code == 422
    errors = {e["field"]: e["message"] for e in refused.json()["errors"]}
    assert errors["signers[0].email"] == "Enter a valid email address"
    assert errors[f"parties.{doc.party('Firm')['id']}"] == "Choose who countersigns as Firm"
    assert errors[f"fields.{doc.field('Effective date')['id']}"] == "Enter a date"
    assert errors["values[1].field_id"] == "Not a field of this document"  # a signature is signed
    assert errors["values[2].field_id"] == "Not a field of this document"

    missing = send(owner, doc, request_for(owner, doc, company, values=[], signers=[]))
    errors = {e["field"]: e["message"] for e in missing.json()["errors"]}
    assert errors[f"fields.{doc.field('Effective date')['id']}"] == "Fill this in before sending"
    assert errors[f"parties.{doc.party('Client')['id']}"] == "Add who signs as Client"


def test_one_person_on_two_parties_is_sent_once_confirmed(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> None:
    doc = sendable(owner, run, detect)
    body = request_for(
        owner,
        doc,
        company,
        signers=[{"party_id": doc.party("Client")["id"], "name": "Rosa", "email": company.email}],
    )

    asked = send(owner, doc, body)
    assert (asked.status_code, asked.json()["code"]) == (409, "same-person")
    assert company.email in asked.json()["detail"]
    assert send(owner, doc, {**body, "confirm_same_person": True}).status_code == 201


def test_unapproved_archived_and_read_only_are_refused(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    make_client: Callable[..., TestClient],
    add_member: Callable[..., Account],
) -> None:
    doc = sendable(owner, run, detect)
    other = new_document(owner, doc.department_id, forms.nda_like(), name="Second NDA").json()
    in_review_id = other["versions"][0]["id"]
    run(in_review_id)
    detect(in_review_id, FakeAssigner())
    in_review = Sendable(other["id"], in_review_id, doc.department_id, {})
    refused = send(
        owner,
        in_review,
        request_for(owner, in_review, company, signers=[], countersigners=[], values=[]),
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "version-not-approved")

    body = request_for(owner, doc, company)
    envelope = send(owner, doc, body).json()
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert send(theirs, doc, body).status_code == 403
        assert theirs.get(f"/api/v1/envelopes/{envelope['id']}").status_code == 403
    assert owner.get(f"/api/v1/envelopes/{uuid.uuid4()}").status_code == 404

    assert owner.post(
        f"{DOCUMENTS}/{doc.document_id}/archive", headers=csrf_headers(owner)
    ).is_success
    archived = send(owner, doc, body)
    assert (archived.status_code, archived.json()["code"]) == (409, "document-archived")


def test_twenty_parties_and_two_hundred_values_send_in_half_a_second(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
) -> None:
    """NFR-E1: the send is written in a constant number of statements and the emails are queued."""
    document_id, version_id = _in_review(owner, run, detect)
    body = _body(_view(owner, document_id, version_id))
    body["parties"] = [
        {"id": str(uuid.uuid4()), "label": f"Signer {n}", "kind": "signer", "kind_label": None}
        for n in range(19)
    ] + [{"id": str(uuid.uuid4()), "label": "Firm", "kind": "countersigner", "kind_label": None}]
    body["fields"] = [
        _drawn(
            f"{p['label']} signature",
            p["id"],
            holds="signature",
            rect=[20, 20 + n * 30, 200, 44 + n * 30],
        )
        for n, p in enumerate(body["parties"])
    ] + [
        _drawn(f"Detail {n}", None, rect=[300, 20 + n * 3.5, 460, 28 + n * 3.5], required=False)
        for n in range(200)
    ]
    assert _save(owner, document_id, version_id, body).status_code == 200
    assert _approve(owner, document_id, version_id).status_code == 204
    doc = Sendable(document_id, version_id, "", _view(owner, document_id, version_id))
    make_countersigner(
        owner,
        owner.get(f"{DOCUMENTS}/{document_id}").json()["department_id"],
        [str(company.user_id)],
    )
    request = request_for(
        owner,
        doc,
        company,
        signers=[
            {"party_id": p["id"], "name": f"Person {n}", "email": f"person{n}@example.com"}
            for n, p in enumerate(doc.view["roles"])
            if p["kind"] == "signer"
        ],
        values=[
            {"field_id": f["id"], "value": f"Value {n}"}
            for n, f in enumerate(doc.view["fields"])
            if f["label"].startswith("Detail")
        ],
    )

    started = time.monotonic()
    sent = send(owner, doc, request)
    elapsed = time.monotonic() - started

    assert sent.status_code == 201, sent.text[:500]
    assert len(sent.json()["values"]) == 200
    assert elapsed < 0.5, f"{elapsed:.2f} s"


def test_the_emails_give_dates_in_the_senders_time_zone(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    doc = sendable(owner, run, detect)
    sent = send(
        owner, doc, {**request_for(owner, doc, company), "time_zone": "America/Los_Angeles"}
    )

    assert sent.status_code == 201, sent.text
    envelope = sent.json()
    address = envelope["recipients"][0]["email"]
    with committing_db.unit_of_work() as uow:
        body = uow.session.execute(
            text(
                "SELECT text_body FROM email_messages WHERE category = 'sign_request' "
                "AND to_address = :a"
            ),
            {"a": address},
        ).scalar_one()
        zone = uow.session.execute(
            text("SELECT time_zone FROM envelopes WHERE id = :e"), {"e": envelope["id"]}
        ).scalar_one()
    assert zone == "America/Los_Angeles"
    expires = datetime.fromisoformat(envelope["expires_at"]).astimezone(ZoneInfo(zone))
    assert f"It expires on {expires:%b} {expires.day}, {expires.year} at " in body
    assert body.split("It expires on", 1)[1].split(".", 1)[0].endswith(("PST", "PDT"))


def test_a_time_zone_the_server_does_not_know_sends_in_utc(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    """The zone only words a date and the sender never typed it: a browser's "Etc/Unknown", or
    the tz database's "localtime" (the server's own zone), is no reason to refuse a send."""
    doc = sendable(owner, run, detect)
    for name in ("Etc/Unknown", "localtime"):
        sent = send(owner, doc, {**request_for(owner, doc, company), "time_zone": name})
        assert sent.status_code == 201, sent.text
        with committing_db.unit_of_work() as uow:
            zone = uow.session.execute(
                text("SELECT time_zone FROM envelopes WHERE id = :e"), {"e": sent.json()["id"]}
            ).scalar_one()
        assert zone == "UTC"


def test_a_dropdown_is_filled_in_from_its_own_options(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
) -> None:
    """A PDF's dropdown is one place carrying its options (kept with it since the Phase 6 review).
    The send form built a choice's options from each place's own option only, so a dropdown
    reached it with none: nothing could be chosen, and a template with a required one could never
    be sent."""
    department = create_department(owner)
    document = new_document(owner, department["id"], forms.all_types()).json()
    document_id, version_id = document["id"], document["versions"][0]["id"]
    run(version_id)
    detect(version_id, FakeAssigner())
    assert _approve(owner, document_id, version_id).status_code == 204
    view = _view(owner, document_id, version_id)
    doc = Sendable(document_id, version_id, department["id"], view)
    dropdown = next(
        f for f in view["fields"] if any(p["kind"] == "combobox" for p in f["placements"])
    )

    form = owner.get(f"{DOCUMENTS}/{document_id}/versions/{version_id}/send-form").json()
    asked = next(f for f in form["fields"] if f["id"] == dropdown["id"])
    assert [o["value"] for o in asked["options"]] == ["California", "New York", "Texas"]

    def body(state: str) -> dict[str, Any]:
        values = [v for v in required_values(owner, doc) if v["field_id"] != dropdown["id"]]
        return {
            "version_id": version_id,
            "signers": [
                {"party_id": p["party_id"], "name": "Maya Chen", "email": "maya@example.com"}
                for p in form["signers"]
            ],
            "values": [*values, {"field_id": dropdown["id"], "value": state}],
            "settings": {"reminder_interval_hours": 24, "max_reminders": 3, "expiry_days": 30},
        }

    refused = send(owner, doc, body("Ohio"))
    assert refused.status_code == 422
    assert [(e["field"], e["message"]) for e in refused.json()["errors"]] == [
        (f"fields.{dropdown['id']}", "Choose one of the options")
    ]
    sent = send(owner, doc, body("Texas"))
    assert sent.status_code == 201, sent.text
    assert {v["field_id"]: v["value"] for v in sent.json()["values"]}[dropdown["id"]] == "Texas"


def _without_signers(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], *, firm: bool
) -> tuple[Sendable, dict[str, Any] | None]:
    """An approved version nobody signs first: with one countersigner party, or with no party."""
    document_id, version_id = _in_review(owner, run, detect)
    body = _body(_view(owner, document_id, version_id))
    theirs = {p["id"] for p in body["parties"]}
    party = {"id": str(uuid.uuid4()), "label": "Firm", "kind": "countersigner", "kind_label": None}
    body["parties"] = [party] if firm else []
    body["fields"] = [
        {**f, "required": False} for f in body["fields"] if f["party_id"] not in theirs
    ]
    if firm:
        body["fields"].append(
            _drawn("Firm signature", party["id"], holds="signature", rect=[300, 600, 480, 636])
        )
    assert _save(owner, document_id, version_id, body).status_code == 200
    assert _approve(owner, document_id, version_id).status_code == 204
    view = _view(owner, document_id, version_id)
    department_id = owner.get(f"{DOCUMENTS}/{document_id}").json()["department_id"]
    return Sendable(document_id, version_id, department_id, view), (party if firm else None)


SETTINGS = {"reminder_interval_hours": 24, "max_reminders": 3, "expiry_days": 30}


def test_with_no_signer_to_wait_for_the_countersigners_are_emailed_at_once(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    """Countersigners wait for every signer. With no signer they waited for nobody, for ever: the
    envelope went out, no one was emailed, and Remind reached no one. Their turn begins at once."""
    doc, _ = _without_signers(owner, run, detect, firm=True)
    firm = doc.party("Firm")

    sent = send(
        owner,
        doc,
        {
            "version_id": doc.version_id,
            "signers": [],
            "countersigners": [{"party_id": firm["id"], "user_id": str(company.user_id)}],
            "settings": SETTINGS,
        },
    )

    assert sent.status_code == 201, sent.text
    (recipient,) = sent.json()["recipients"]
    assert (recipient["kind"], recipient["status"]) == ("countersigner", "sent")
    assert recipient["delivery"]["status"] == "queued"  # emailed their link
    with committing_db.unit_of_work() as uow:
        emailed = uow.session.execute(
            text(
                "SELECT count(*) FROM email_messages WHERE category = 'sign_request' "
                "AND dedupe_key = :k"
            ),
            {"k": f"sign_request:{recipient['id']}:1"},
        ).scalar_one()
    assert emailed == 1
    reminded = owner.post(
        f"/api/v1/envelopes/{sent.json()['id']}/remind",
        headers={**csrf_headers(owner), **idempotency_key()},
    )
    assert reminded.json() == {"reminded": 1}


def test_a_version_nobody_signs_is_not_sent(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    """With no party at all there is nobody to ask: the send is refused, in words that say what to
    do. Review still only warns (it never blocks an approval)."""
    doc, _ = _without_signers(owner, run, detect, firm=False)

    refused = send(owner, doc, {"version_id": doc.version_id, "signers": [], "settings": SETTINGS})

    assert (refused.status_code, refused.json()["code"]) == (409, "nobody-signs")
    assert (
        refused.json()["title"] == "Nobody signs this template. Add who signs and where, then send"
    )
