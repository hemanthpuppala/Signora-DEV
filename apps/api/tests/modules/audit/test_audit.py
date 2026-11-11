"""Audit log tests (backbone LLD §4.8)."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from signora.kernel.context import Origin, set_origin
from signora.kernel.db import Database
from signora.modules.audit import Actor, AuditChain, Subject, record, verify
from signora.modules.audit.domain import (
    GENESIS_HASH,
    AuditEntry,
    canonical_ip,
    canonical_timestamp,
    check_data,
    compute_hash,
)
from tests.conftest import TEST_DATABASE

USER = Actor("user", uuid.uuid4(), "Hemanth Puppala <hp@example.com>")


def new_chain() -> AuditChain:
    return AuditChain.envelope(uuid.uuid4(), uuid.uuid4())


def record_many(db: Database, chain: AuditChain, count: int) -> None:
    for n in range(count):
        with db.unit_of_work() as uow:
            record(uow, chain=chain, actor=USER, action="test.recorded", data={"n": n})


@contextmanager
def triggers_disabled(db: Database) -> Iterator[None]:
    """Simulates an attacker with full database control (owner can disable triggers)."""
    with db.unit_of_work() as uow:
        uow.session.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
    try:
        yield
    finally:
        with db.unit_of_work() as uow:
            uow.session.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))


def test_recorded_entries_form_a_verifiable_chain(committing_db: Database) -> None:
    chain = new_chain()
    subject = Subject("envelope", chain.chain_id)
    with committing_db.unit_of_work() as uow:
        first = record(uow, chain=chain, actor=USER, action="envelope.sent", subject=subject)
        second = record(uow, chain=chain, actor=Actor.system(), action="reminder.sent")

    assert (first.seq, second.seq) == (1, 2)
    with committing_db.unit_of_work() as uow:
        result = verify(uow.session, chain.chain_id)
    assert result.ok
    assert result.entries_checked == 2
    assert result.head_seq == 2
    assert result.head_hash == second.hash


def test_request_origin_is_attached_automatically(committing_db: Database) -> None:
    chain = new_chain()
    set_origin(Origin("req-0001-abcd", "::ffff:203.0.113.7", "Safari iOS"))
    try:
        with committing_db.unit_of_work() as uow:
            entry = record(uow, chain=chain, actor=USER, action="recipient.signed")
    finally:
        set_origin(None)

    assert (entry.request_id, entry.ip, entry.user_agent) == (
        "req-0001-abcd",
        "203.0.113.7",
        "Safari iOS",
    )
    with committing_db.unit_of_work() as uow:
        assert verify(uow.session, chain.chain_id).ok  # inet round trip keeps the hash stable


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("2001:0db8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
        (None, None),
    ],
)
def test_ip_canonical_form(raw: str | None, canonical: str | None) -> None:
    assert canonical_ip(raw) == canonical


def test_ipv6_round_trip_verifies(committing_db: Database) -> None:
    chain = new_chain()
    set_origin(Origin(None, "2001:0db8:0000:0000:0000:0000:0000:0001", None))
    try:
        with committing_db.unit_of_work() as uow:
            record(uow, chain=chain, actor=USER, action="recipient.opened")
    finally:
        set_origin(None)
    with committing_db.unit_of_work() as uow:
        assert verify(uow.session, chain.chain_id).ok


def test_floats_and_unsupported_types_are_rejected() -> None:
    with pytest.raises(TypeError, match="floating-point"):
        check_data({"fee": 33.3})
    with pytest.raises(TypeError, match="unsupported"):
        check_data({"when": datetime.now(UTC)})
    check_data({"fee_basis_points": 3330, "ok": True, "items": [None, "a"], "nested": {"k": 1}})


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        canonical_timestamp(datetime(2026, 11, 7))  # noqa: DTZ001 - the point of the test


def test_rolled_back_action_leaves_no_entry(committing_db: Database) -> None:
    chain = new_chain()
    with pytest.raises(RuntimeError), committing_db.unit_of_work() as uow:
        record(uow, chain=chain, actor=USER, action="envelope.sent")
        raise RuntimeError

    with committing_db.unit_of_work() as uow:
        result = verify(uow.session, chain.chain_id)
    assert result.ok and result.entries_checked == 0


def test_failed_attempt_is_kept_with_commit_then_raise(committing_db: Database) -> None:
    """LLD §7.1a: a failed signing-code attempt is recorded even though the request fails."""
    chain = new_chain()
    with pytest.raises(PermissionError), committing_db.unit_of_work() as uow:
        record(uow, chain=chain, actor=USER, action="otp.failed", data={"attempt": 1})
        uow.commit()
        raise PermissionError("wrong code")

    with committing_db.unit_of_work() as uow:
        assert verify(uow.session, chain.chain_id).entries_checked == 1


def test_changed_entry_is_detected_at_its_position(committing_db: Database) -> None:
    chain = new_chain()
    record_many(committing_db, chain, 3)
    with triggers_disabled(committing_db), committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE audit_events SET data = '{\"n\": 99}' WHERE chain_id = :c AND seq = 2"),
            {"c": chain.chain_id},
        )

    with committing_db.unit_of_work() as uow:
        result = verify(uow.session, chain.chain_id)
    assert not result.ok
    assert result.failed_seq == 2


def test_deleted_middle_entry_shows_as_a_gap(committing_db: Database) -> None:
    chain = new_chain()
    record_many(committing_db, chain, 3)
    with triggers_disabled(committing_db), committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("DELETE FROM audit_events WHERE chain_id = :c AND seq = 2"), {"c": chain.chain_id}
        )

    with committing_db.unit_of_work() as uow:
        result = verify(uow.session, chain.chain_id)
    assert not result.ok
    assert result.failed_seq == 2
    assert result.reason == "entry 2 is missing"


def test_truncation_is_caught_only_by_the_anchored_head(committing_db: Database) -> None:
    chain = new_chain()
    record_many(committing_db, chain, 3)
    with committing_db.unit_of_work() as uow:
        anchor = verify(uow.session, chain.chain_id)  # e.g. printed on a certificate
    with triggers_disabled(committing_db), committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("DELETE FROM audit_events WHERE chain_id = :c AND seq = 3"), {"c": chain.chain_id}
        )

    with committing_db.unit_of_work() as uow:
        alone = verify(uow.session, chain.chain_id)
        anchored = verify(
            uow.session, chain.chain_id, expected_head=(anchor.head_seq, anchor.head_hash)
        )
    assert alone.ok  # no gap: the chain by itself cannot reveal it
    assert not anchored.ok
    assert anchored.reason is not None and "truncated" in anchored.reason


def test_fifty_concurrent_appends_stay_contiguous(committing_db: Database) -> None:
    chain = new_chain()
    errors: list[BaseException] = []

    def append(n: int) -> None:
        try:
            with committing_db.unit_of_work() as uow:
                record(uow, chain=chain, actor=USER, action="test.concurrent", data={"n": n})
        except BaseException as error:  # surfaced by the assertion below
            errors.append(error)

    threads = [threading.Thread(target=append, args=(n,)) for n in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with committing_db.unit_of_work() as uow:
        seqs = list(
            uow.session.execute(
                text("SELECT seq FROM audit_events WHERE chain_id = :c ORDER BY seq"),
                {"c": chain.chain_id},
            ).scalars()
        )
        result = verify(uow.session, chain.chain_id)
    assert seqs == list(range(1, 51))
    assert result.ok


def test_different_chains_do_not_wait_on_each_other(committing_db: Database) -> None:
    busy, other = new_chain(), new_chain()
    holding, release = threading.Event(), threading.Event()

    def hold_busy_chain() -> None:
        with committing_db.unit_of_work() as uow:
            record(uow, chain=busy, actor=USER, action="test.slow")
            holding.set()
            release.wait(timeout=10)  # keeps the busy chain's lock

    holder = threading.Thread(target=hold_busy_chain)
    holder.start()
    assert holding.wait(timeout=5)
    started = time.monotonic()
    with committing_db.unit_of_work() as uow:
        record(uow, chain=other, actor=USER, action="test.fast")
    elapsed = time.monotonic() - started
    release.set()
    holder.join()

    assert elapsed < 1.0


def test_system_and_workspace_chains(committing_db: Database) -> None:
    workspace = uuid.uuid4()
    with committing_db.unit_of_work() as uow:
        system_entry = record(
            uow, chain=AuditChain.system(), actor=Actor.system(), action="workspace.signed_up"
        )
        ws_entry = record(
            uow, chain=AuditChain.workspace(workspace), actor=USER, action="member.invited"
        )

    assert system_entry.chain.workspace_id == uuid.UUID(int=0)
    assert ws_entry.chain.chain_id == ws_entry.chain.workspace_id == workspace
    with committing_db.unit_of_work() as uow:
        assert verify(uow.session, workspace).ok
        assert verify(uow.session, AuditChain.system().chain_id).ok


def test_hash_covers_every_field() -> None:
    chain = new_chain()
    base = AuditEntry(
        chain=chain,
        seq=1,
        occurred_at=datetime(2026, 11, 7, tzinfo=UTC),
        actor=USER,
        action="envelope.sent",
        subject=None,
        request_id="r",
        ip="203.0.113.7",
        user_agent="ua",
        data={"a": 1},
    )
    reference = compute_hash(GENESIS_HASH, base)
    variants: list[dict[str, Any]] = [
        {"seq": 2},
        {"action": "envelope.cancelled"},
        {"ip": "203.0.113.8"},
        {"user_agent": "other"},
        {"request_id": "other"},
        {"data": {"a": 2}},
        {"actor": Actor("user", USER.id, "Someone Else")},
        {"occurred_at": datetime(2026, 11, 7, 0, 0, 1, tzinfo=UTC)},
    ]
    for change in variants:
        changed = dataclasses.replace(base, **change)
        assert compute_hash(GENESIS_HASH, changed) != reference, change


def test_cli_verify_reports_and_sets_exit_code(committing_db: Database) -> None:
    chain = new_chain()
    record_many(committing_db, chain, 2)
    environment = {**os.environ, "POSTGRES_DB": TEST_DATABASE}
    command = [sys.executable, "-m", "signora.entrypoints.cli", "audit", "verify"]

    ok = subprocess.run(
        [*command, str(chain.chain_id)], env=environment, capture_output=True, text=True
    )
    report = json.loads(ok.stdout)
    assert ok.returncode == 0
    assert report["ok"] is True and report["entries_checked"] == 2

    bad = subprocess.run(
        [*command, str(chain.chain_id), "--expect-seq", "5", "--expect-hash", "00" * 32],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 1
    assert "truncated" in json.loads(bad.stdout)["reason"]
