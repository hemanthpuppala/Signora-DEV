"""A department's envelopes (Phase 7 LLD §6, §10, NFR-E6)."""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from signora.modules.envelopes import store
from tests.modules.documents.conftest import DEPARTMENTS, csrf_headers, log_in
from tests.modules.envelopes.conftest import sendable
from tests.modules.envelopes.test_send import request_for, send
from tests.modules.identity_access.conftest import Account


def test_the_list_is_newest_first_with_its_signers_filtered_and_paged(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = sendable(owner, run, detect)
    ids = []
    for name in ("Ada", "Ben", "Cy"):
        signers = [
            {"party_id": doc.party("Client")["id"], "name": name, "email": f"{name}@example.com"}
        ]
        sent = send(owner, doc, request_for(owner, doc, company, signers=signers))
        ids.append(sent.json()["id"])
    owner.post(f"/api/v1/envelopes/{ids[0]}/cancel", headers=csrf_headers(owner))
    listing = f"{DEPARTMENTS}/{doc.department_id}/envelopes"

    page = owner.get(listing).json()

    assert [e["id"] for e in page["envelopes"]] == ids[::-1]
    assert page["next_cursor"] is None
    newest = page["envelopes"][0]
    assert (newest["signers"], newest["signed"], newest["status"]) == (["Cy"], 0, "sent")
    cancelled = owner.get(listing, params={"status": "cancelled"}).json()["envelopes"]
    assert [e["id"] for e in cancelled] == [ids[0]]
    counts = owner.get(f"{DEPARTMENTS}/{doc.department_id}").json()["counts"]
    assert counts == {"sent": 2, "signed": 0, "pending": 2}  # a withdrawn send is not counted
    home = {d["id"]: d["counts"] for d in owner.get(DEPARTMENTS).json()}
    assert home[doc.department_id] == counts

    monkeypatch.setattr(store, "PAGE", 2)
    first = owner.get(listing).json()
    second = owner.get(listing, params={"cursor": first["next_cursor"]}).json()
    assert [e["id"] for e in first["envelopes"] + second["envelopes"]] == ids[::-1]
    assert second["next_cursor"] is None
    assert owner.get(listing, params={"cursor": "not a cursor"}).status_code == 422


def test_only_people_who_may_see_sends_list_them(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    make_client: Callable[..., TestClient],
    add_member: Callable[..., Account],
) -> None:
    doc = sendable(owner, run, detect)
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert theirs.get(f"{DEPARTMENTS}/{doc.department_id}/envelopes").status_code == 403
    missing = owner.get(f"{DEPARTMENTS}/01a1c000-0000-7000-8000-000000000000/envelopes")
    assert missing.status_code == 404


def test_a_thousand_envelopes_list_in_under_200_ms(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    """NFR-E6: the list reads one index range, whatever the department's size."""
    doc = sendable(owner, run, detect)
    first = send(owner, doc, request_for(owner, doc, company)).json()
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "INSERT INTO envelopes (workspace_id, department_id, document_id, version_id, "
                "title, require_email_code, reminder_interval_hours, max_reminders, expires_at, "
                "notify_emails, sent_by, sent_at) SELECT workspace_id, department_id, "
                "document_id, version_id, title || ' ' || n, require_email_code, "
                "reminder_interval_hours, max_reminders, expires_at, notify_emails, sent_by, "
                "sent_at - make_interval(mins => n) "
                "FROM envelopes, generate_series(1, 1000) AS n WHERE id = :e"
            ),
            {"e": first["id"]},
        )
        uow.session.execute(text("ANALYZE envelopes, envelope_recipients"))

    started = time.monotonic()
    page = owner.get(f"{DEPARTMENTS}/{doc.department_id}/envelopes")
    elapsed = time.monotonic() - started

    assert page.status_code == 200
    assert len(page.json()["envelopes"]) == store.PAGE and page.json()["next_cursor"]
    assert elapsed < 0.2, f"{elapsed:.3f} s"
