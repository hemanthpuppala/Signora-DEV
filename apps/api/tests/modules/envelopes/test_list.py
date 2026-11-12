"""A department's envelopes (Phase 7 LLD §6, §10, NFR-E6)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

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
    # a withdrawn send is not counted
    assert counts == {"sent": 2, "signed": 0, "pending": 2, "to_approve": 0}
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

    # And it reads only its page. The index was by state, so the default list read all 1 001
    # envelopes of the department, joined each to its recipients and sorted them, for every page.
    with committing_db.unit_of_work() as uow:
        plan = uow.session.execute(
            text("EXPLAIN (ANALYZE, FORMAT JSON) " + store.LIST_SQL),
            {
                "w": company.workspace_id,
                "dep": doc.department_id,
                "status": None,
                "at": None,
                "id": None,
                "n": store.PAGE + 1,
            },
        ).scalar_one()

    def read(node: dict[str, Any], table: str) -> int:
        own = (
            node["Actual Rows"] * node["Actual Loops"] if node.get("Relation Name") == table else 0
        )
        return own + sum(read(child, table) for child in node.get("Plans", ()))

    assert read(plan[0]["Plan"], "envelopes") == store.PAGE + 1


def test_a_search_finds_envelopes_by_their_customer_or_template_best_match_first(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR S-1: a signer's name or email, the template's name or the title; typos forgiven; the
    envelope's other people (copies) are not its customers."""
    doc = sendable(owner, run, detect)
    sent = {}
    for name, email in (
        ("Ada Lovelace", "ada@analytical.example"),
        ("Ben Okafor", "ben.okafor@lagos.example"),
        ("Adam Smith", "adam@wealth.example"),
    ):
        signers = [{"party_id": doc.party("Client")["id"], "name": name, "email": email}]
        answer = send(owner, doc, request_for(owner, doc, company, signers=signers))
        sent[name] = answer.json()["id"]
    listing = f"{DEPARTMENTS}/{doc.department_id}/envelopes"

    def found(q: str) -> list[str]:
        envelopes = owner.get(listing, params={"q": q}).json()["envelopes"]
        return [e["signers"][0] for e in envelopes]

    assert found("lovlace") == ["Ada Lovelace"]  # a typo
    assert found("OKAFOR@LAGOS") == ["Ben Okafor"]  # part of an email, any case
    assert found("ada") == ["Adam Smith", "Ada Lovelace"]  # both contain it: newest first
    assert found("records@firm") == []  # a copy, not a customer
    template = owner.get(f"{DEPARTMENTS}/{doc.department_id}/documents").json()[0]["name"]
    assert len(found(template)) == 3  # by the template's name

    monkeypatch.setattr(store, "PAGE", 1)  # page through the matches: none twice, none missed
    seen: list[str] = []
    cursor = None
    while True:
        params = {"q": "a", **({"cursor": cursor} if cursor else {})}
        page = owner.get(listing, params=params).json()
        seen += [e["id"] for e in page["envelopes"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(sent.values())
