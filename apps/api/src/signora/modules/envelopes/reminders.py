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
from signora.modules.envelopes.schedule import DELIVERABLE, OPEN, STILL_TO_ACT
from signora.modules.notifications import spare_capacity

log = get_logger("signora.envelopes.reminders")

SWEEP = "envelopes.remind_due"
EVERY = timedelta(minutes=5)
BATCH = 100  # envelopes per pass
# Reminders can wait; a sign request or an email code cannot. Reminders use at most this share of
# the daily email limit, so the rest is always there for mail a person is waiting for.
REMINDER_SHARE = 0.7

# A due schedule nobody can be reminded on (signed, declined, the envelope closed or expired, the
# maximum reached, their last email failed): cleared, so the index holds only live schedules.
# Constants, never input.
_CLEAR_DEAD = (
    "UPDATE envelope_recipients r SET next_reminder_at = NULL FROM envelopes e "  # noqa: S608
    "WHERE e.id = r.envelope_id AND r.next_reminder_at <= now() AND NOT ("
    f"r.status IN {STILL_TO_ACT} AND e.status IN {OPEN} AND e.expires_at > now() "
    f"AND r.reminders_sent < e.max_reminders AND {DELIVERABLE})"
)


def remind_due(database: Database) -> int:
    """Remind everyone due now, within the reminders' share of the daily email limit; how many
    were emailed. Whoever is left over, and an envelope that fails (logged), stay due for the next
    sweep with their schedule unchanged; the others still go. O(log N + due)."""
    with database.unit_of_work() as uow:
        uow.session.execute(text(_CLEAR_DEAD))
        budget = spare_capacity(uow.session, REMINDER_SHARE)
    if budget <= 0:
        return 0  # the day's reminder share is spent: everyone due stays due
    reminded = 0
    seen: set[uuid.UUID] = set()  # each envelope once a sweep, reminded or not: the loop ends
    while budget > reminded:
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
            if reminded >= budget:
                break
            seen.add(envelope_id)
            try:
                with database.unit_of_work() as uow:
                    reminded += service.remind_automatically(
                        uow, envelope_id, workspace_id, at_most=budget - reminded
                    )
            except Exception:  # one envelope's data never stops the others' reminders
                log.exception("reminders.envelope_failed", envelope_id=str(envelope_id))
        if len(due) < BATCH:
            return reminded
    log.warning("reminders.waiting_for_capacity", reminded=reminded)  # the rest: next sweeps
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
