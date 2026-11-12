"""Automatic reminders (reminders LLD): who is reminded, when, how often, and when never."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from signora.modules.envelopes import (
    every_signer_signed,
    lock_envelope,
    recipient_for_signing,
    record_opened,
    reminders,
)
from signora.modules.envelopes.reminders import remind_due
from signora.modules.envelopes.schedule import schedule_next
from signora.modules.notifications import service as notifications_service
from signora.modules.notifications import spare_capacity
from tests.modules.documents.conftest import csrf_headers
from tests.modules.envelopes.conftest import sendable
from tests.modules.envelopes.test_follow import ENVELOPES, emails_to, post, sent_envelope
from tests.modules.envelopes.test_send import request_for, send
from tests.modules.identity_access.conftest import Account

INTERVAL = timedelta(hours=48)  # request_for's settings: every 48 hours, at most 3, 30 days


def _schedule(db: Database, recipient_id: str) -> Any:
    with db.unit_of_work() as uow:
        return uow.session.execute(
            text(
                "SELECT next_reminder_at, reminders_sent, now() AS now FROM envelope_recipients "
                "WHERE id = :r"
            ),
            {"r": recipient_id},
        ).one()


def _due(db: Database, recipient_id: str) -> None:
    with db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "UPDATE envelope_recipients SET next_reminder_at = now() - interval '1 minute' "
                "WHERE id = :r"
            ),
            {"r": recipient_id},
        )


def _run(db: Database, sql: str, **params: object) -> None:
    with db.unit_of_work() as uow:
        uow.session.execute(text(sql), params)


def _reminders(db: Database, address: str) -> list[Any]:
    return [e for e in emails_to(db, address) if e.category == "sign_reminder"]


def _about(moment: datetime, expected: datetime) -> bool:
    return abs(moment - expected) < timedelta(minutes=1)


def test_a_signer_is_reminded_once_when_due_and_then_an_interval_later(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer, firm, _ = envelope["recipients"]
    first = _schedule(committing_db, signer["id"])
    assert _about(first.next_reminder_at, first.now + INTERVAL)  # scheduled at the send
    assert _schedule(committing_db, firm["id"]).next_reminder_at is None  # not their turn yet
    page = owner.get(f"{ENVELOPES}/{envelope['id']}").json()
    assert page["recipients"][0]["next_reminder_at"] is not None
    assert page["recipients"][1]["next_reminder_at"] is None

    _due(committing_db, signer["id"])
    remind_due(committing_db)
    remind_due(committing_db)  # nothing more is due

    (reminder,) = _reminders(committing_db, signer["email"])
    assert "still waiting for you to sign" in reminder.text_body
    after = _schedule(committing_db, signer["id"])
    assert after.reminders_sent == 1
    assert _about(after.next_reminder_at, after.now + INTERVAL)
    entry = owner.get(f"{ENVELOPES}/{envelope['id']}").json()["timeline"][0]
    assert (entry["action"], entry["by"], entry["data"]) == (
        "envelope.reminded",
        None,
        {"recipients": 1, "recipient_ids": [signer["id"]], "automatic": True},
    )


def test_no_reminder_past_the_maximum_after_signing_or_once_closed_or_expired(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    cases = {
        "maximum": "UPDATE envelope_recipients SET reminders_sent = 3 WHERE id = :r",
        "signed": "UPDATE envelope_recipients SET status = 'signed', signed_at = now() "
        "WHERE id = :r",
        "declined": "UPDATE envelopes SET status = 'declined' WHERE id = :e",
        "expired": "UPDATE envelopes SET expires_at = now() - interval '1 second' WHERE id = :e",
    }
    doc = sendable(owner, run, detect)
    signers = {}
    for case, sql in cases.items():
        address = f"{case}-{uuid.uuid4().hex[:8]}@example.com"
        people = [{"party_id": doc.party("Client")["id"], "name": "Maya Chen", "email": address}]
        response = send(owner, doc, request_for(owner, doc, company, signers=people))
        assert response.status_code == 201, response.text
        envelope = response.json()
        signer = envelope["recipients"][0]
        _due(committing_db, signer["id"])
        _run(committing_db, sql, r=signer["id"], e=envelope["id"])
        signers[case] = signer

    remind_due(committing_db)

    for case, signer in signers.items():
        assert not _reminders(committing_db, signer["email"]), case
        assert _schedule(committing_db, signer["id"]).next_reminder_at is None, case  # cleared


def test_a_cancelled_envelope_is_never_reminded(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer = envelope["recipients"][0]

    assert post(owner, f"{ENVELOPES}/{envelope['id']}/cancel").status_code == 200
    _due(committing_db, signer["id"])
    remind_due(committing_db)

    assert not _reminders(committing_db, signer["email"])
    assert _schedule(committing_db, signer["id"]).next_reminder_at is None


def test_the_last_reminder_before_the_expiry_says_when_the_link_stops(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer = envelope["recipients"][0]
    _due(committing_db, signer["id"])
    _run(
        committing_db,
        "UPDATE envelopes SET expires_at = now() + interval '20 hours' WHERE id = :e",
        e=envelope["id"],
    )

    remind_due(committing_db)

    (reminder,) = _reminders(committing_db, signer["email"])
    assert reminder.text_body.count("this link stops working") == 1
    assert _schedule(committing_db, signer["id"]).next_reminder_at is None  # past the expiry


def test_a_reminder_by_hand_moves_the_next_automatic_one(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer = envelope["recipients"][0]
    _due(committing_db, signer["id"])

    assert post(owner, f"{ENVELOPES}/{envelope['id']}/remind").status_code == 200
    remind_due(committing_db)

    assert len(_reminders(committing_db, signer["email"])) == 1  # by hand only
    after = _schedule(committing_db, signer["id"])
    assert after.reminders_sent == 1
    assert _about(after.next_reminder_at, after.now + INTERVAL)


def test_a_corrected_email_and_a_countersigners_turn_start_their_schedule(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer, firm, _ = envelope["recipients"]
    _due(committing_db, signer["id"])
    _run(  # the mistyped address used up every reminder
        committing_db,
        "UPDATE envelope_recipients SET reminders_sent = 3 WHERE id = :r",
        r=signer["id"],
    )

    changed = owner.patch(
        f"{ENVELOPES}/{envelope['id']}/recipients/{signer['id']}",
        json={"email": f"new-{signer['email']}"},
        headers=csrf_headers(owner),
    )
    assert changed.status_code == 200, changed.text
    moved = _schedule(committing_db, signer["id"])
    assert moved.reminders_sent == 0  # the new address starts afresh
    assert _about(moved.next_reminder_at, moved.now + INTERVAL)
    _due(committing_db, signer["id"])
    remind_due(committing_db)
    assert len(_reminders(committing_db, f"new-{signer['email']}")) == 1

    _run(
        committing_db,
        "UPDATE envelope_recipients SET status = 'signed', signed_at = now() WHERE id = :r",
        r=signer["id"],
    )
    with committing_db.unit_of_work() as uow:
        assert every_signer_signed(uow.session, envelope["id"]) == [uuid.UUID(firm["id"])]
    turn = _schedule(committing_db, firm["id"])
    assert _about(turn.next_reminder_at, turn.now + INTERVAL)


def test_two_sweeps_at_once_send_one_reminder(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    """Both sweeps find the person due, then queue on the envelope's lock; the second re-checks
    under it and finds nothing due. One email, one count, one timeline entry (audit events are
    not deduplicated, so a second reminder would show)."""
    _, envelope = sent_envelope(owner, run, detect, company)
    signer = envelope["recipients"][0]
    _due(committing_db, signer["id"])

    sweeps = [threading.Thread(target=remind_due, args=(committing_db,)) for _ in range(2)]
    with committing_db.unit_of_work() as held:  # both reach the envelope while it is held
        lock_envelope(held.session, uuid.UUID(envelope["id"]))
        for sweep in sweeps:
            sweep.start()
        for sweep in sweeps:
            sweep.join(timeout=0.5)
        assert all(sweep.is_alive() for sweep in sweeps)  # both waiting on the envelope
    for sweep in sweeps:
        sweep.join(timeout=10)

    assert len(_reminders(committing_db, signer["email"])) == 1
    assert _schedule(committing_db, signer["id"]).reminders_sent == 1
    with committing_db.unit_of_work() as uow:
        entries = uow.session.execute(
            text(
                "SELECT count(*) FROM audit_events WHERE subject_id = :e "
                "AND action = 'envelope.reminded'"
            ),
            {"e": envelope["id"]},
        ).scalar_one()
    assert entries == 1


def test_reminders_use_only_their_share_of_the_daily_email_limit(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reminders can wait; sign requests and email codes cannot (reminders LLD, review of #35)."""
    with committing_db.unit_of_work() as uow:
        used = uow.session.execute(
            text(
                "SELECT count(*) FROM email_messages WHERE status = 'queued' "
                "OR (status = 'sent' AND sent_at > now() - interval '24 hours')"
            )
        ).scalar_one()
        monkeypatch.setattr(notifications_service, "_default_daily_limit", lambda: used + 10)
        assert spare_capacity(uow.session, 1.0) == 10
        assert spare_capacity(uow.session, 0.0) == 0  # never below nothing

    doc = sendable(owner, run, detect)
    people = []
    for name in ("first", "second"):
        address = f"{name}-{uuid.uuid4().hex[:8]}@example.com"
        signers = [{"party_id": doc.party("Client")["id"], "name": "Maya Chen", "email": address}]
        response = send(owner, doc, request_for(owner, doc, company, signers=signers))
        assert response.status_code == 201, response.text
        people.append(response.json()["recipients"][0])
        _due(committing_db, people[-1]["id"])
    monkeypatch.setattr(reminders, "spare_capacity", lambda _session, _share: 1)

    assert remind_due(committing_db) == 1

    sent = [len(_reminders(committing_db, p["email"])) for p in people]
    assert sorted(sent) == [0, 1]
    left = people[sent.index(0)]
    assert _schedule(committing_db, left["id"]).next_reminder_at is not None  # due next sweep


def test_an_open_waits_for_the_envelope_before_it_locks_the_person(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    """The lock order of the sweep (envelope, then its people) is every writer's: an open that
    locked the person first and then waited for the envelope would deadlock with a reminder."""
    _, envelope = sent_envelope(owner, run, detect, company)
    signer = envelope["recipients"][0]

    def open_link() -> None:
        with committing_db.unit_of_work() as uow:
            recipient = recipient_for_signing(uow.session, uuid.UUID(signer["id"]))
            assert recipient is not None
            record_opened(uow.session, recipient)

    with committing_db.unit_of_work() as sweep:  # a reminder holding the envelope
        lock_envelope(sweep.session, uuid.UUID(envelope["id"]))
        opening = threading.Thread(target=open_link)
        opening.start()
        opening.join(timeout=0.5)  # waiting on the envelope
        assert opening.is_alive()
        with committing_db.unit_of_work() as other:  # the person's row is still free
            other.session.execute(
                text("SELECT 1 FROM envelope_recipients WHERE id = :r FOR UPDATE NOWAIT"),
                {"r": signer["id"]},
            )
    opening.join(timeout=5)
    assert not opening.is_alive()
    assert _schedule(committing_db, signer["id"]).next_reminder_at is not None
    with committing_db.unit_of_work() as uow:
        status = uow.session.execute(
            text("SELECT status FROM envelope_recipients WHERE id = :r"), {"r": signer["id"]}
        ).scalar_one()
    assert status == "opened"


def test_a_failed_address_is_not_reminded_until_it_is_sent_again(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer = envelope["recipients"][0]
    _run(
        committing_db,
        "UPDATE email_messages SET status = 'failed', failed_at = now(), last_error = 'bounced', "
        "text_body = NULL, html_body = NULL "
        "WHERE id = (SELECT last_email_id FROM envelope_recipients WHERE id = :r)",
        r=signer["id"],
    )
    page = owner.get(f"{ENVELOPES}/{envelope['id']}").json()
    assert page["recipients"][0]["next_reminder_at"] is None  # not promised while it fails
    _due(committing_db, signer["id"])

    remind_due(committing_db)

    assert not _reminders(committing_db, signer["email"])
    assert _schedule(committing_db, signer["id"]).next_reminder_at is None  # cleared
    again = post(owner, f"{ENVELOPES}/{envelope['id']}/recipients/{signer['id']}/resend")
    assert again.status_code in (200, 204), again.text
    restarted = _schedule(committing_db, signer["id"])
    assert _about(restarted.next_reminder_at, restarted.now + INTERVAL)


def test_no_reminder_is_scheduled_within_an_hour_of_the_expiry(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    _, envelope = sent_envelope(owner, run, detect, company)
    signer = envelope["recipients"][0]
    for expires, scheduled in (("48 hours 30 minutes", False), ("49 hours 30 minutes", True)):
        _run(
            committing_db,
            "UPDATE envelopes SET expires_at = now() + CAST(:x AS interval) WHERE id = :e",
            x=expires,
            e=envelope["id"],
        )
        with committing_db.unit_of_work() as uow:
            schedule_next(uow.session, [uuid.UUID(signer["id"])])
        assert (_schedule(committing_db, signer["id"]).next_reminder_at is not None) == scheduled
