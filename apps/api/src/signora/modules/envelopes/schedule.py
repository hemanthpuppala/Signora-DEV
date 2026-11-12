"""When each person is reminded next (reminders LLD §4): one interval after they were last emailed
their link or a reminder, while the envelope allows more and before it expires.

The rule for ``next_reminder_at``; the sweep (``reminders``) only reads and clears it, cancelling
clears it, and migration 0034 applied the same rule to the envelopes already out.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection

from sqlalchemy import text
from sqlalchemy.orm import Session

# Holds a working link and has not signed or declined (the service's LIVE).
STILL_TO_ACT = "('sent', 'opened', 'viewed')"
# An envelope its people can still act on: ``signed`` is the countersigners' turn.
OPEN = "('sent', 'opened', 'viewed', 'signed')"
# Their last email reached them, or is still on its way: a failed address is not reminded (the
# page offers Send again, which schedules them afresh). ``r`` is envelope_recipients.
DELIVERABLE = (
    "NOT EXISTS (SELECT 1 FROM email_messages m WHERE m.id = r.last_email_id "
    "AND m.status = 'failed')"
)
# One interval from now, if the maximum is not reached and it leaves at least an hour before the
# expiry: a last-chance reminder always leaves time to sign (and the sweep's few minutes of delay
# never push it past the expiry).
NEXT = (
    "CASE WHEN r.reminders_sent < e.max_reminders "
    "AND now() + make_interval(hours => e.reminder_interval_hours) "
    "<= e.expires_at - interval '1 hour' "
    "THEN now() + make_interval(hours => e.reminder_interval_hours) END"
)


def schedule_next(session: Session, recipient_ids: Collection[uuid.UUID]) -> None:
    """Each person was emailed just now: their next reminder is one interval on, or none."""
    if not recipient_ids:
        return
    session.execute(
        text(
            # STILL_TO_ACT and NEXT are constants of this module, never input.
            f"UPDATE envelope_recipients r SET next_reminder_at = {NEXT} "  # noqa: S608
            f"FROM envelopes e WHERE e.id = r.envelope_id AND r.id = ANY(:ids) "
            f"AND r.status IN {STILL_TO_ACT}"
        ),
        {"ids": list(recipient_ids)},
    )
