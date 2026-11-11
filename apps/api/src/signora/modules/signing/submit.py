"""Submit (Phase 8 LLD §6): everything checked again on the server, under the envelope's lock, then
the person's values written once.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import text

from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, ValidationFailed
from signora.modules.envelopes import (
    asked,
    every_signer_signed,
    fits,
    lock_envelope,
    recipient_for_signing,
    record_signed,
    unsigned,
    write_values,
)
from signora.modules.identity_access import normalize_email
from signora.modules.review.formats import InvalidValueError, check_value
from signora.modules.signing import consent, signatures
from signora.modules.signing.document import SIGNING_DATE, SIGNS
from signora.modules.signing.drafts import SIGNED, merged_values
from signora.modules.signing.errors import AlreadySigned, LinkClosed, NotTheirTurn
from signora.modules.signing.service import Signer
from signora.modules.signing.trail import audit


class Submitted(BaseModel):
    signed_at: datetime
    next: str = "done"


def _signed_on(uow: UnitOfWork, time_zone: str) -> str:
    """Today, as the envelope's zone has it: a signing date is the day the person signed where the
    sender is (the envelope's dates are all in that zone, Phase 7 §5)."""
    now: datetime = uow.session.execute(text("SELECT now()")).scalar_one()
    return now.astimezone(ZoneInfo(time_zone)).date().isoformat()


def submit(uow: UnitOfWork, who: Signer) -> Submitted:
    """O(F + P + V). Raises ``ValidationFailed`` naming each field that is not right, and writes
    nothing then."""
    lock_envelope(uow.session, who.recipient.envelope_id)
    recipient = recipient_for_signing(uow.session, who.recipient.id)
    if recipient is None or not recipient.envelope_open:
        raise LinkClosed
    if recipient.status == "signed" and recipient.signed_at is not None:
        return Submitted(signed_at=recipient.signed_at)  # a repeat: the same answer
    if recipient.status == "declined":
        raise AlreadySigned
    if recipient.kind == "countersigner" and recipient.envelope_status != "signed":
        raise NotTheirTurn

    m = merged_values(uow, Signer(recipient, who.verified, who.digest))
    items, merged, locked = m.items, m.values, m.locked
    now_asked = asked(items, merged)
    adopted = signatures.adopted(uow, recipient.id)
    signed_on = _signed_on(uow, recipient.time_zone)
    errors: list[FieldError] = []
    given: list[tuple[uuid.UUID, str]] = []
    for item in items:
        if item.party_id is None or item.party_id != recipient.party_id or item.id not in now_asked:
            continue
        value = merged.get(item.id, "")
        if item.holds == SIGNING_DATE:
            given.append((item.id, signed_on))
            continue
        if item.holds in SIGNS:
            mark = adopted.get(item.holds)
            if value == SIGNED and mark is not None:
                given.append((item.id, f"{item.holds}:{mark.signature_id}"))
            else:
                errors.append(
                    FieldError(
                        str(item.id), "Sign here" if item.holds == "signature" else "Initial here"
                    )
                )
            continue
        if item.id in locked:
            given.append((item.id, value))  # their own name, or what was given before sending
            continue
        if not value:
            if item.id in m.required:
                errors.append(FieldError(str(item.id), "Fill this in"))
            continue
        try:
            value = check_value(
                item.holds,
                value,
                options=[option.value for option in item.options],
                normalize_email=normalize_email,
            )
        except InvalidValueError as error:
            errors.append(FieldError(str(item.id), str(error)))
            continue
        if not fits(item, value, recipient.font):
            errors.append(FieldError(str(item.id), "Too long for its box"))
            continue
        given.append((item.id, value))
    if errors:
        raise ValidationFailed(errors, detail="Some of your fields need attention")

    write_values(uow.session, recipient, given)
    signed_at = record_signed(uow.session, recipient)
    if signed_at is None:  # signed a moment ago under another request: the lock makes this rare
        raise AlreadySigned
    uow.session.execute(
        text("DELETE FROM signing_drafts WHERE recipient_id = :r"), {"r": recipient.id}
    )
    audit(
        uow,
        recipient,
        "signing.signed",
        verified_by="email_code" if recipient.require_email_code else "email_link",
        disclosure_version=consent.VERSION,
        values_sha256=_digest(given),
        signatures=",".join(sorted(mark.signature_id for mark in adopted.values())),
    )
    if recipient.kind == "signer" and unsigned(uow.session, recipient.envelope_id, "signer") == 0:
        every_signer_signed(uow.session, recipient.envelope_id)
        audit(uow, recipient, "envelope.signers_signed")
    return Submitted(signed_at=signed_at)


def _digest(given: list[tuple[uuid.UUID, str]]) -> str:
    canonical = json.dumps(sorted((str(f), v) for f, v in given), separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
