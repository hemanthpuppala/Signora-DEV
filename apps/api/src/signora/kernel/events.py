"""Domain events as a thin layer over jobs (backbone LLD §1.5).

``publish`` runs inside the business transaction and enqueues one job per subscriber
(``event:<EventName>:<subscriber>``, deduplicated by event id). Each subscriber retries on its own,
and there is no separate events table: the event is the payload of its jobs.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from signora.kernel.jobs import DeadHandler, JobContext, JobKind, JobRegistry, enqueue, registry
from signora.kernel.logging import get_logger

log = get_logger("signora.events")

DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_LEASE = timedelta(minutes=2)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DomainEvent(BaseModel):
    """Base class for events. Subclasses add their own fields; all must be JSON-serialisable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    occurred_at: datetime = Field(default_factory=_utc_now)
    workspace_id: uuid.UUID | None = None

    name: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.name = cls.__name__


EventHandler = Callable[[JobContext, Any], None]


class EventBus:
    def __init__(self, jobs_registry: JobRegistry) -> None:
        self._registry = jobs_registry
        self._event_types: dict[str, type[DomainEvent]] = {}
        self._subscribers: dict[str, list[str]] = {}

    @staticmethod
    def job_kind(event_name: str, subscriber: str) -> str:
        return f"event:{event_name}:{subscriber}"

    def subscribe[E: DomainEvent](
        self,
        event_type: type[E],
        subscriber: str,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        lease: timedelta = DEFAULT_LEASE,
        on_dead: DeadHandler | None = None,
    ) -> Callable[[Callable[[JobContext, E], None]], Callable[[JobContext, E], None]]:
        """Register ``handler(context, event)`` as ``subscriber``'s reaction to ``event_type``.
        ``on_dead(uow, payload)`` settles what the handler left when its job dies (backbone §1.4);
        the payload is the event as JSON."""
        known = self._event_types.setdefault(event_type.name, event_type)
        if known is not event_type:
            raise ValueError(f"two event classes are named {event_type.name!r}")

        def decorator(
            handler: Callable[[JobContext, E], None],
        ) -> Callable[[JobContext, E], None]:
            def run(context: JobContext) -> None:
                handler(context, event_type.model_validate(context.payload))

            self._registry.register(
                JobKind(
                    self.job_kind(event_type.name, subscriber),
                    run,
                    max_attempts=max_attempts,
                    lease=lease,
                    on_dead=on_dead,
                )
            )
            subscribers = self._subscribers.setdefault(event_type.name, [])
            if subscriber in subscribers:
                raise ValueError(f"{subscriber!r} already subscribes to {event_type.name}")
            subscribers.append(subscriber)
            return handler

        return decorator

    def subscribers(self, event_type: type[DomainEvent]) -> tuple[str, ...]:
        return tuple(self._subscribers.get(event_type.name, ()))

    def publish(self, session: Session, event: DomainEvent) -> int:
        """Enqueue one job per subscriber in the caller's transaction. Returns jobs enqueued."""
        payload = event.model_dump(mode="json")
        enqueued = 0
        for subscriber in self._subscribers.get(event.name, ()):
            if enqueue(
                session,
                self.job_kind(event.name, subscriber),
                payload,
                dedupe_key=f"event:{event.event_id}:{subscriber}",
                jobs_registry=self._registry,
            ):
                enqueued += 1
        log.debug("event.published", event_name=event.name, subscribers=enqueued)
        return enqueued


bus = EventBus(registry)
"""Application-wide event bus, backed by the application job registry."""
