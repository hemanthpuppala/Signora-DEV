"""When each person is reminded next (reminders LLD §4): one interval after they were last emailed
their link or a reminder, while the envelope allows more and before it expires.

The only place ``next_reminder_at`` is set; the sweep (``reminders``) only reads and clears it.
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
# One interval from now, if it falls before the expiry and the maximum is not reached.
NEXT = (
    "CASE WHEN r.reminders_sent < e.max_reminders "
    "AND now() + make_interval(hours => e.reminder_interval_hours) < e.expires_at "
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
