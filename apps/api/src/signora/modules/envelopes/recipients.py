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

from signora.modules.envelopes.schedule import schedule_next

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
    document_name: str  # the template's name, as the signer's screen shows it
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
                   e.require_email_code, e.title, d.name AS document_name, e.time_zone, e.font,
                   w.name AS company,
                   u.name AS sender_name, u.email AS sender_email
            FROM envelope_recipients r
            JOIN envelopes e ON e.id = r.envelope_id
            JOIN workspaces w ON w.id = r.workspace_id
            JOIN users u ON u.id = e.sent_by
            JOIN documents d ON d.id = e.document_id
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


def lock_envelope(session: Session, envelope_id: uuid.UUID) -> None:
    """The envelope's row lock (Phase 8 §6.2): every submit, decline and cancel of one envelope
    takes it first, so they apply one at a time and exactly one submit is the last."""
    session.execute(text("SELECT 1 FROM envelopes WHERE id = :e FOR UPDATE"), {"e": envelope_id})


def write_values(
    session: Session, recipient: SignerRecipient, values: list[tuple[uuid.UUID, str]]
) -> None:
    """What a person gave, as the envelope's values (Phase 8 §6.3.1). A field that already holds
    a value given before signing (a prefilled email) keeps it."""
    if not values:
        return
    session.execute(
        text(
            """
            INSERT INTO envelope_values (envelope_id, workspace_id, version_id, field_id, value,
                                         given_by, recipient_id)
            SELECT :e, :w, :v, field_id, value, 'recipient', :r
            FROM unnest(CAST(:fields AS uuid[]), CAST(:values AS text[])) AS t(field_id, value)
            ON CONFLICT (envelope_id, field_id) DO NOTHING
            """
        ),
        {
            "e": recipient.envelope_id,
            "w": recipient.workspace_id,
            "v": recipient.version_id,
            "r": recipient.id,
            "fields": [field_id for field_id, _ in values],
            "values": [value for _, value in values],
        },
    )


def record_signed(session: Session, recipient: SignerRecipient) -> datetime | None:
    """The person has signed: once (a guarded update). The time it was recorded, or ``None`` when
    they had already signed or declined."""
    signed: datetime | None = session.execute(
        text(
            "UPDATE envelope_recipients SET status = 'signed', signed_at = now() "
            "WHERE id = :r AND status NOT IN ('signed', 'declined') RETURNING signed_at"
        ),
        {"r": recipient.id},
    ).scalar_one_or_none()
    return signed


def unsigned(session: Session, envelope_id: uuid.UUID, kind: str) -> int:
    """How many of the envelope's people of a kind have still to sign (by the envelope's index)."""
    count: int = session.execute(
        text(
            "SELECT count(*) FROM envelope_recipients "
            "WHERE envelope_id = :e AND kind = :k AND status <> 'signed'"
        ),
        {"e": envelope_id, "k": kind},
    ).scalar_one()
    return count


def every_signer_signed(session: Session, envelope_id: uuid.UUID) -> list[uuid.UUID]:
    """Every signer has signed (Phase 8 §6.3.5): the envelope is ``signed`` and its countersigners
    move from ``waiting`` to ``sent``. Returns those countersigners, to be emailed."""
    session.execute(
        text(
            "UPDATE envelopes SET status = 'signed' WHERE id = :e AND status IN "
            "('sent', 'opened', 'viewed')"
        ),
        {"e": envelope_id},
    )
    rows = session.execute(
        text(
            "UPDATE envelope_recipients SET status = 'sent', sent_at = now() "
            "WHERE envelope_id = :e AND kind = 'countersigner' AND status = 'waiting' "
            "RETURNING id"
        ),
        {"e": envelope_id},
    )
    turned = [row.id for row in rows]
    schedule_next(session, turned)
    return turned


@dataclass(frozen=True)
class Person:
    name: str
    email: str


@dataclass(frozen=True)
class Contacts:
    """Whom an envelope's news goes to besides its recipients: the sender and the Also notify list
    (Phase 7 §4), and where its page is."""

    department_id: uuid.UUID
    sender: Person
    notify: list[str]


def envelope_contacts(session: Session, envelope_id: uuid.UUID) -> Contacts:
    row = session.execute(
        text(
            "SELECT e.department_id, e.notify_emails, u.name, u.email FROM envelopes e "
            "JOIN users u ON u.id = e.sent_by WHERE e.id = :e"
        ),
        {"e": envelope_id},
    ).one()
    return Contacts(row.department_id, Person(row.name, row.email), list(row.notify_emails))


def people(session: Session, recipient_ids: list[uuid.UUID]) -> list[tuple[uuid.UUID, Person]]:
    rows = session.execute(
        text(
            "SELECT id, name, email FROM envelope_recipients WHERE id = ANY(:ids) "
            "ORDER BY stage, position"
        ),
        {"ids": recipient_ids},
    )
    return [(row.id, Person(row.name, row.email)) for row in rows]


@dataclass(frozen=True)
class Declined:
    """Who is told of a decline (Phase 8 §8.2): the sender and the Also notify list with the
    reason; every other person already emailed without it."""

    contacts: Contacts
    others: list[Person]


def record_declined(session: Session, recipient: SignerRecipient, reason: str) -> Declined | None:
    """The person declines, and with them the envelope (final). ``None`` when they had already
    signed or declined (a guarded update): a repeat changes nothing."""
    done = session.execute(
        text(
            "UPDATE envelope_recipients SET status = 'declined', declined_at = now(), "
            "decline_reason = :why WHERE id = :r AND status NOT IN ('signed', 'declined') "
            "RETURNING id"
        ),
        {"r": recipient.id, "why": reason},
    ).one_or_none()
    if done is None:
        return None
    session.execute(
        text("UPDATE envelopes SET status = 'declined' WHERE id = :e"),
        {"e": recipient.envelope_id},
    )
    others = session.execute(
        text(
            "SELECT name, email FROM envelope_recipients WHERE envelope_id = :e AND id <> :r "
            "AND kind IN ('signer', 'countersigner') AND status <> 'waiting' "
            "ORDER BY stage, position"
        ),
        {"e": recipient.envelope_id, "r": recipient.id},
    )
    return Declined(
        contacts=envelope_contacts(session, recipient.envelope_id),
        others=[Person(row.name, row.email) for row in others],
    )
