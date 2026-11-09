"""How envelopes read in the API (Phase 7 LLD §6, §10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

EnvelopeStatus = Literal[
    "sent", "opened", "viewed", "signed", "completed", "declined", "expired", "cancelled"
]
RecipientStatus = Literal["waiting", "sent", "opened", "viewed", "signed", "declined"]


class PersonRef(BaseModel):
    id: uuid.UUID
    name: str


class Delivery(BaseModel):
    """Their last email: queued, sent, or failed (with why)."""

    status: Literal["queued", "sent", "failed"]
    error: str | None


class RecipientView(BaseModel):
    id: uuid.UUID
    kind: Literal["signer", "countersigner", "copy"]
    party_id: uuid.UUID | None
    party_label: str | None
    name: str
    email: str
    status: RecipientStatus
    sent_at: datetime | None
    opened_at: datetime | None
    viewed_at: datetime | None
    signed_at: datetime | None
    delivery: Delivery | None


class ValueView(BaseModel):
    field_id: uuid.UUID
    value: str
    given_by: Literal["sender", "prefill", "recipient"]


class TimelineEntry(BaseModel):
    at: datetime
    action: str
    by: str | None  # a person's name, or None for the system
    data: dict[str, object]


class EnvelopeView(BaseModel):
    id: uuid.UUID
    title: str
    status: EnvelopeStatus
    department_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    version_id: uuid.UUID
    version_number: int
    sent_by: PersonRef
    sent_at: datetime
    expires_at: datetime
    cancelled_at: datetime | None
    require_email_code: bool
    reminder_interval_hours: int
    max_reminders: int
    notify_emails: list[str]
    recipients: list[RecipientView]
    values: list[ValueView]
    timeline: list[TimelineEntry]


class EnvelopeSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: EnvelopeStatus
    document_id: uuid.UUID
    document_name: str
    version_number: int
    signers: list[str]  # the signers' names, in signing order
    signed: int  # how many signers have signed
    sent_at: datetime
    expires_at: datetime


class EnvelopePage(BaseModel):
    envelopes: list[EnvelopeSummary]
    next_cursor: str | None
