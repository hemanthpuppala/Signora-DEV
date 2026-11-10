"""Following a send: remind, resend, correct, cancel, copy a link (Phase 7 LLD §6, §10)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.config import get_settings
from signora.kernel.db import Database
from signora.modules.envelopes.links import link_key, read_token
from tests.modules.documents.conftest import csrf_headers, log_in
from tests.modules.envelopes.conftest import Sendable, sendable
from tests.modules.envelopes.test_send import request_for, send
from tests.modules.identity_access.conftest import Account, idempotency_key

ENVELOPES = "/api/v1/envelopes"
KEY = link_key(get_settings().app.secret_key.get_secret_value())


def sent_envelope(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> tuple[Sendable, dict[str, Any]]:
    doc = sendable(owner, run, detect)
    address = f"maya-{uuid.uuid4().hex[:8]}@example.com"  # the database keeps earlier tests' mail
    signers = [{"party_id": doc.party("Client")["id"], "name": "Maya Chen", "email": address}]
    response = send(owner, doc, request_for(owner, doc, company, signers=signers))
    assert response.status_code == 201, response.text
    return doc, response.json()


def emails_to(db: Database, address: str) -> list[Any]:
    with db.unit_of_work() as uow:
        return list(
            uow.session.execute(
                text(
                    "SELECT category, text_body, reply_to FROM email_messages "
                    "WHERE to_address = :a ORDER BY created_at"
                ),
                {"a": address},
            )
        )


def link_in(body: str) -> Any:
    found = re.search(r"/s/([A-Za-z0-9_-]+)", body)
    assert found is not None
    return read_token(KEY, found.group(1))


def post(api: TestClient, path: str, **kwargs: Any) -> Any:
    return api.post(path, headers={**csrf_headers(api), **idempotency_key()}, **kwargs)


def test_remind_emails_who_still_has_to_sign_and_never_the_waiting_firm(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)

    reminded = post(owner, f"{ENVELOPES}/{envelope['id']}/remind")

    assert (reminded.status_code, reminded.json()) == (200, {"reminded": 1})
    categories = [e.category for e in emails_to(committing_db, envelope["recipients"][0]["email"])]
    assert categories == ["sign_request", "sign_reminder"]
    assert not [
        e for e in emails_to(committing_db, company.email) if e.category.startswith("sign_")
    ]
    after = owner.get(f"{ENVELOPES}/{envelope['id']}").json()
    assert after["timeline"][0]["action"] == "envelope.reminded"


def test_one_person_can_be_reminded_but_never_a_countersigner_before_their_turn(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer, firm, _ = envelope["recipients"]

    reminded = post(owner, f"{ENVELOPES}/{envelope['id']}/recipients/{signer['id']}/remind")

    assert (reminded.status_code, reminded.json()) == (200, {"reminded": 1})
    assert [e.category for e in emails_to(committing_db, signer["email"])] == [
        "sign_request",
        "sign_reminder",
    ]
    entry = owner.get(f"{ENVELOPES}/{envelope['id']}").json()["timeline"][0]
    assert (entry["action"], entry["data"]["recipient_id"]) == ("envelope.reminded", signer["id"])
    waiting = post(owner, f"{ENVELOPES}/{envelope['id']}/recipients/{firm['id']}/remind")
    assert (waiting.status_code, waiting.json()["code"]) == (409, "not-their-turn")


def test_resend_emails_the_same_link_and_waits_for_a_countersigners_turn(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer, firm, _ = envelope["recipients"]

    assert (
        post(owner, f"{ENVELOPES}/{envelope['id']}/recipients/{signer['id']}/resend").status_code
        == 200
    )
    first, again = emails_to(committing_db, envelope["recipients"][0]["email"])
    assert link_in(first.text_body) == link_in(again.text_body)  # the same link
    waiting = post(owner, f"{ENVELOPES}/{envelope['id']}/recipients/{firm['id']}/resend")
    assert (waiting.status_code, waiting.json()["code"]) == (409, "not-their-turn")


def test_a_corrected_email_stops_the_old_link_and_sends_a_new_one(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    doc, envelope = sent_envelope(owner, run, detect, company)
    signer, firm, _ = envelope["recipients"]
    old = link_in(emails_to(committing_db, signer["email"])[0].text_body)
    new_address = f"maya.chen-{uuid.uuid4().hex[:8]}@example.org"

    changed = owner.patch(
        f"{ENVELOPES}/{envelope['id']}/recipients/{signer['id']}",
        json={"email": new_address.upper()},
        headers=csrf_headers(owner),
    )

    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["recipients"][0]["email"] == new_address
    (email,) = emails_to(committing_db, new_address)
    new = link_in(email.text_body)
    assert (new.recipient_id, old.link_version, new.link_version) == (old.recipient_id, 1, 2)
    with committing_db.unit_of_work() as uow:
        version = uow.session.execute(
            text("SELECT link_version FROM envelope_recipients WHERE id = :r"), {"r": signer["id"]}
        ).scalar_one()
    assert version == 2  # the old link names version 1: refused from now on
    prefilled = {v["field_id"]: v for v in body["values"] if v["given_by"] == "prefill"}
    emails_fields = [
        f["id"]
        for f in doc.view["fields"]
        if f["party_id"] == signer["party_id"] and f["holds"] == "email"
    ]
    assert all(prefilled[f]["value"] == new_address for f in emails_fields)
    assert body["timeline"][0]["action"] == "envelope.recipient_changed"

    colleague = owner.patch(
        f"{ENVELOPES}/{envelope['id']}/recipients/{firm['id']}",
        json={"email": "someone@else.example"},
        headers=csrf_headers(owner),
    )
    assert colleague.status_code == 422  # a countersigner's email is their account's
    with committing_db.unit_of_work() as uow:  # once opened, the name stays as sent
        uow.session.execute(
            text("UPDATE envelope_recipients SET status = 'opened' WHERE id = :r"),
            {"r": signer["id"]},
        )
    renamed = owner.patch(
        f"{ENVELOPES}/{envelope['id']}/recipients/{signer['id']}",
        json={"name": "Maya C."},
        headers=csrf_headers(owner),
    )
    assert renamed.status_code == 422


def test_cancel_stops_every_link_tells_the_signers_and_closes_the_envelope(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer = envelope["recipients"][0]

    cancelled = owner.post(f"{ENVELOPES}/{envelope['id']}/cancel", headers=csrf_headers(owner))

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert [e.category for e in emails_to(committing_db, envelope["recipients"][0]["email"])] == [
        "sign_request",
        "sign_withdrawn",
    ]
    with committing_db.unit_of_work() as uow:
        live = uow.session.execute(
            text(
                "SELECT count(*) FROM envelope_recipients "
                "WHERE envelope_id = :e AND revoked_at IS NULL"
            ),
            {"e": envelope["id"]},
        ).scalar_one()
    assert live == 0
    again = owner.post(f"{ENVELOPES}/{envelope['id']}/cancel", headers=csrf_headers(owner))
    assert again.status_code == 200  # repeat-safe
    closed = post(owner, f"{ENVELOPES}/{envelope['id']}/remind")
    assert (closed.status_code, closed.json()["code"]) == (409, "envelope-closed")
    link = owner.get(f"{ENVELOPES}/{envelope['id']}/recipients/{signer['id']}/link")
    assert link.status_code == 409


def test_copy_signing_link_shows_the_current_link_and_is_audited(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer, firm, _ = envelope["recipients"]

    copied = owner.get(f"{ENVELOPES}/{envelope['id']}/recipients/{signer['id']}/link")

    assert copied.status_code == 200
    emailed = link_in(emails_to(committing_db, envelope["recipients"][0]["email"])[0].text_body)
    assert link_in(copied.json()["url"]) == emailed
    assert (
        owner.get(f"{ENVELOPES}/{envelope['id']}").json()["timeline"][0]["action"]
        == "envelope.link_copied"
    )
    waiting = owner.get(f"{ENVELOPES}/{envelope['id']}/recipients/{firm['id']}/link")
    assert (waiting.status_code, waiting.json()["code"]) == (409, "not-their-turn")


def test_people_without_send_access_cannot_follow_up(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    make_client: Callable[..., TestClient],
    add_member: Callable[..., Account],
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert post(theirs, f"{ENVELOPES}/{envelope['id']}/remind").status_code == 403
        assert (
            theirs.post(
                f"{ENVELOPES}/{envelope['id']}/cancel", headers=csrf_headers(theirs)
            ).status_code
            == 403
        )


def test_an_envelope_shows_its_document_after_the_document_is_archived(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    make_client: Callable[..., TestClient],
    add_member: Callable[..., Account],
) -> None:
    doc, envelope = sent_envelope(owner, run, detect, company)
    path = f"{ENVELOPES}/{envelope['id']}/document"
    before = owner.get(path)
    assert before.status_code == 200, before.text
    drawn = {f["id"]: f for f in before.json()["fields"]}
    # What is typed or comes from the signer is drawn; a signature is not a typed value.
    assert drawn[doc.field("Effective date")["id"]]["places"][0]["rect"] == [300, 40, 400, 60]
    assert drawn[doc.field("Client printed name")["id"]]["from_recipient"] == "name"
    assert doc.field("Firm signature")["id"] not in drawn
    assert before.json()["pages"] and before.json()["fit"]["min_size"] > 0

    documents = "/api/v1/documents"
    archived = owner.post(f"{documents}/{doc.document_id}/archive", headers=csrf_headers(owner))
    assert archived.json()["archived_at"] is not None
    # Sending it again is refused; the send already out is unaffected.
    form = owner.get(f"{documents}/{doc.document_id}/versions/{doc.version_id}/send-form")
    assert (form.status_code, form.json()["code"]) == (409, "document-archived")
    assert owner.get(path).json() == before.json()

    viewer = add_member(company, role="read")  # may not see sends: nor their documents
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert theirs.get(path).status_code == 403
    assert owner.get(f"{ENVELOPES}/{uuid.uuid4()}/document").status_code == 404
