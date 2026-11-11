"""A recipient as signing sees them (Phase 8 LLD §1, §16): who they are, their envelope's state, and
the moves signing makes on envelope rows. Envelopes owns these tables; signing calls these
functions and never writes them itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

# An envelope a signer may still act on (Phase 7 §1.1). Past its expiry it is closed to them even
# before Phase 10 moves its status (Phase 8 §1.1.9).
OPEN_STATUSES = frozenset({"sent", "opened", "viewed", "signed"})


@dataclass(frozen=True)
class SignerRecipient:
    id: uuid.UUID
    workspace_id: uuid.UUID
    envelope_id: uuid.UUID
    version_id: uuid.UUID
    party_id: uuid.UUID | None
    kind: str  # signer, countersigner, copy
    status: str
    name: str
    email: str
    user_id: uuid.UUID | None
    link_version: int
    revoked: bool
    signed_at: datetime | None
    envelope_status: str
    expired: bool  # now is at or past the envelope's expiry
    require_email_code: bool
    title: str
    time_zone: str
    font: str
    company: str
    sender_name: str
    sender_email: str

    @property
    def envelope_open(self) -> bool:
        return self.envelope_status in OPEN_STATUSES and not self.expired and not self.revoked


def recipient_for_signing(session: Session, recipient_id: uuid.UUID) -> SignerRecipient | None:
    """The recipient, their envelope and who sent it, in one read by primary keys. O(1)."""
    row = session.execute(
        text(
            """
            SELECT r.id, r.workspace_id, r.envelope_id, r.version_id, r.party_id, r.kind,
                   r.status, r.name, r.email, r.user_id, r.link_version,
                   r.revoked_at IS NOT NULL AS revoked,
                   r.signed_at, e.status AS envelope_status, e.expires_at <= now() AS expired,
                   e.require_email_code, e.title, e.time_zone, e.font, w.name AS company,
                   u.name AS sender_name, u.email AS sender_email
            FROM envelope_recipients r
            JOIN envelopes e ON e.id = r.envelope_id
            JOIN workspaces w ON w.id = r.workspace_id
            JOIN users u ON u.id = e.sent_by
            WHERE r.id = :r
            """
        ),
        {"r": recipient_id},
    ).one_or_none()
    return SignerRecipient(**row._mapping) if row is not None else None


def record_opened(session: Session, recipient: SignerRecipient) -> bool:
    """The first accepted open (Phase 8 §1.1.5): the recipient is ``opened`` and the envelope too
    while it is ``sent``. ``True`` only for the open that recorded it, so two opens at the same
    moment record it once. Statuses only move forward."""
    opened = session.execute(
        text(
            "UPDATE envelope_recipients SET opened_at = now(), "
            "status = CASE WHEN status = 'sent' THEN 'opened' ELSE status END "
            "WHERE id = :r AND opened_at IS NULL RETURNING id"
        ),
        {"r": recipient.id},
    ).one_or_none()
    if opened is None:
        return False
    session.execute(
        text("UPDATE envelopes SET status = 'opened' WHERE id = :e AND status = 'sent'"),
        {"e": recipient.envelope_id},
    )
    return True


def record_viewed(session: Session, recipient: SignerRecipient) -> bool:
    """The document first shown to the person (Phase 8 §4.5): ``viewed``, and the envelope too
    while it is ``opened``. Once; statuses only move forward."""
    viewed = session.execute(
        text(
            "UPDATE envelope_recipients SET viewed_at = now(), "
            "status = CASE WHEN status IN ('sent', 'opened') THEN 'viewed' ELSE status END "
            "WHERE id = :r AND viewed_at IS NULL RETURNING id"
        ),
        {"r": recipient.id},
    ).one_or_none()
    if viewed is None:
        return False
    session.execute(
        text(
            "UPDATE envelopes SET status = 'viewed' WHERE id = :e AND status IN ('sent', 'opened')"
        ),
        {"e": recipient.envelope_id},
    )
    return True


@dataclass(frozen=True)
class GivenValue:
    """A value an envelope holds, with who gave it (Phase 7 §2, Phase 8 §6)."""

    field_id: uuid.UUID
    value: str
    given_by: str  # sender, prefill, recipient
    recipient_id: uuid.UUID | None
    recipient_kind: str | None  # signer or countersigner, for a recipient's own value


def envelope_values(session: Session, envelope_id: uuid.UUID) -> list[GivenValue]:
    """Every value of the envelope, one indexed read (its primary key's first column). O(V)."""
    rows = session.execute(
        text(
            "SELECT v.field_id, v.value, v.given_by, v.recipient_id, r.kind AS recipient_kind "
            "FROM envelope_values v LEFT JOIN envelope_recipients r ON r.id = v.recipient_id "
            "WHERE v.envelope_id = :e"
        ),
        {"e": envelope_id},
    )
    return [GivenValue(**row._mapping) for row in rows]
