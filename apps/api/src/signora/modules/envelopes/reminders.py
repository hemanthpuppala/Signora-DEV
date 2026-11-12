"""Automatic reminders (reminders LLD): a sweep every few minutes emails everyone whose reminder is
due, each envelope in its own transaction under the lock a reminder by hand takes."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import text

from signora.kernel.db import Database
from signora.kernel.jobs import JobContext, JobKind, JobRegistry, RecurringJob
from signora.kernel.logging import get_logger
from signora.modules.envelopes import service
from signora.modules.envelopes.schedule import OPEN, STILL_TO_ACT

log = get_logger("signora.envelopes.reminders")

SWEEP = "envelopes.remind_due"
EVERY = timedelta(minutes=5)
BATCH = 100  # envelopes per pass

# A due schedule nobody can be reminded on (signed, declined, the envelope closed or expired, the
# maximum reached): cleared, so the index holds only live schedules. Constants, never input.
_CLEAR_DEAD = (
    "UPDATE envelope_recipients r SET next_reminder_at = NULL FROM envelopes e "  # noqa: S608
    "WHERE e.id = r.envelope_id AND r.next_reminder_at <= now() AND NOT ("
    f"r.status IN {STILL_TO_ACT} AND e.status IN {OPEN} AND e.expires_at > now() "
    "AND r.reminders_sent < e.max_reminders)"
)


def remind_due(database: Database) -> int:
    """Remind everyone due now; how many were emailed. One envelope that fails is logged and left
    for the next sweep (its schedule is unchanged); the others still go. O(log N + due)."""
    with database.unit_of_work() as uow:
        uow.session.execute(text(_CLEAR_DEAD))
    reminded = 0
    seen: set[uuid.UUID] = set()  # each envelope once a sweep, reminded or not: the loop ends
    while True:
        with database.unit_of_work() as uow:
            due = uow.session.execute(
                text(
                    "SELECT envelope_id, workspace_id FROM envelope_recipients "
                    "WHERE next_reminder_at <= now() "
                    "AND NOT envelope_id = ANY(CAST(:seen AS uuid[])) "
                    "GROUP BY envelope_id, workspace_id ORDER BY min(next_reminder_at) LIMIT :n"
                ),
                {"seen": list(seen), "n": BATCH},
            ).all()
        for envelope_id, workspace_id in due:
            seen.add(envelope_id)
            try:
                with database.unit_of_work() as uow:
                    reminded += service.remind_automatically(uow, envelope_id, workspace_id)
            except Exception:  # one envelope's data never stops the others' reminders
                log.exception("reminders.envelope_failed", envelope_id=str(envelope_id))
        if len(due) < BATCH:
            return reminded


def _sweep(context: JobContext) -> None:
    reminded = remind_due(context.database)
    with context.complete():
        pass
    if reminded:
        log.info("reminders.sent", reminded=reminded)


def register(jobs_registry: JobRegistry) -> RecurringJob:
    jobs_registry.register(JobKind(SWEEP, _sweep, max_attempts=1, lease=timedelta(minutes=5)))
    return RecurringJob(SWEEP, every=EVERY)
