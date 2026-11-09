"""Domain event tests (backbone LLD §1.5, §1.9)."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from signora.kernel.config import DatabaseSettings
from signora.kernel.db import Database, UnitOfWork
from signora.kernel.events import DomainEvent, EventBus
from signora.kernel.jobs import JobContext, JobRegistry
from tests.support.workers import running_worker, wait_until


class _Signed(DomainEvent):
    recipient_id: uuid.UUID


def make_event_type() -> type[_Signed]:
    """A uniquely named event class per test, so tests never share job kinds."""
    return type(f"Signed{uuid.uuid4().hex[:8]}", (_Signed,), {})


def statuses(db: Database, kind: str) -> list[str]:
    with db.unit_of_work() as uow:
        return list(
            uow.session.execute(text("SELECT status FROM jobs WHERE kind = :k"), {"k": kind})
            .scalars()
            .all()
        )


def test_publish_fans_out_one_job_per_subscriber_and_round_trips_the_event(
    committing_db: Database, test_db_settings: DatabaseSettings
) -> None:
    bus = EventBus(JobRegistry())
    event_type = make_event_type()
    received: dict[str, DomainEvent] = {}
    lock = threading.Lock()

    @bus.subscribe(event_type, "notifications")
    def notify(_: JobContext, event: DomainEvent) -> None:
        with lock:
            received["notifications"] = event

    @bus.subscribe(event_type, "envelopes")
    def advance(_: JobContext, event: DomainEvent) -> None:
        with lock:
            received["envelopes"] = event

    recipient = uuid.uuid4()
    event = event_type(recipient_id=recipient, workspace_id=uuid.uuid4())
    with committing_db.unit_of_work() as uow:
        assert bus.publish(uow.session, event) == 2

    with running_worker(committing_db, test_db_settings, bus._registry):
        wait_until(lambda: len(received) == 2)

    assert received["notifications"] == event
    assert received["envelopes"] == event
    assert received["envelopes"].occurred_at.tzinfo is not None


def test_a_failing_subscriber_does_not_affect_the_others(
    committing_db: Database, test_db_settings: DatabaseSettings, no_backoff: None
) -> None:
    bus = EventBus(JobRegistry())
    event_type = make_event_type()

    @bus.subscribe(event_type, "good")
    def good(_: JobContext, __: DomainEvent) -> None:
        return None

    @bus.subscribe(event_type, "bad", max_attempts=2)
    def bad(_: JobContext, __: DomainEvent) -> None:
        raise RuntimeError("subscriber failure")

    with committing_db.unit_of_work() as uow:
        bus.publish(uow.session, event_type(recipient_id=uuid.uuid4()))

    good_kind = EventBus.job_kind(event_type.name, "good")
    bad_kind = EventBus.job_kind(event_type.name, "bad")
    with running_worker(committing_db, test_db_settings, bus._registry):
        wait_until(lambda: statuses(committing_db, bad_kind) == ["dead"])

    assert statuses(committing_db, good_kind) == ["succeeded"]


def test_publishing_the_same_event_twice_enqueues_once(committing_db: Database) -> None:
    bus = EventBus(JobRegistry())
    event_type = make_event_type()
    bus.subscribe(event_type, "only")(lambda ctx, event: None)
    event = event_type(recipient_id=uuid.uuid4())

    with committing_db.unit_of_work() as uow:
        first = bus.publish(uow.session, event)
        second = bus.publish(uow.session, event)

    assert (first, second) == (1, 0)


def test_publish_is_rolled_back_with_the_business_transaction(committing_db: Database) -> None:
    bus = EventBus(JobRegistry())
    event_type = make_event_type()
    bus.subscribe(event_type, "only")(lambda ctx, event: None)

    with pytest.raises(RuntimeError), committing_db.unit_of_work() as uow:
        bus.publish(uow.session, event_type(recipient_id=uuid.uuid4()))
        raise RuntimeError

    assert statuses(committing_db, EventBus.job_kind(event_type.name, "only")) == []


def test_event_without_subscribers_is_a_no_op(committing_db: Database) -> None:
    bus = EventBus(JobRegistry())
    with committing_db.unit_of_work() as uow:
        assert bus.publish(uow.session, make_event_type()(recipient_id=uuid.uuid4())) == 0


def test_duplicate_subscription_and_name_clash_are_rejected() -> None:
    bus = EventBus(JobRegistry())
    event_type = make_event_type()
    bus.subscribe(event_type, "s")(lambda ctx, event: None)

    with pytest.raises(ValueError, match="already"):
        bus.subscribe(event_type, "s")(lambda ctx, event: None)
    clash = type(event_type.name, (DomainEvent,), {})
    with pytest.raises(ValueError, match="two event classes"):
        bus.subscribe(clash, "t")


def test_events_are_immutable_and_timestamped_in_utc() -> None:
    event = make_event_type()(recipient_id=uuid.uuid4())

    assert event.occurred_at <= datetime.now(UTC)
    with pytest.raises(ValueError, match="frozen"):
        event.workspace_id = uuid.uuid4()  # type: ignore[misc]


def test_a_subscribers_dead_job_is_settled_with_its_event(
    committing_db: Database, test_db_settings: DatabaseSettings, no_backoff: None
) -> None:
    bus = EventBus(JobRegistry())
    event_type = make_event_type()
    settled: list[str] = []

    def settle(uow: UnitOfWork, payload: dict[str, Any]) -> None:
        settled.append(payload["recipient_id"])

    @bus.subscribe(event_type, "fails", max_attempts=1, on_dead=settle)
    def fails(_: JobContext, __: DomainEvent) -> None:
        raise RuntimeError("always")

    recipient = uuid.uuid4()
    with committing_db.unit_of_work() as uow:
        bus.publish(uow.session, event_type(recipient_id=recipient))
    kind = EventBus.job_kind(event_type.name, "fails")
    with running_worker(committing_db, test_db_settings, bus._registry):
        wait_until(lambda: statuses(committing_db, kind) == ["dead"])

    assert settled == [str(recipient)]
