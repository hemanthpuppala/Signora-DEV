"""What the signer's page reads (Phase 8 LLD §1.5)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from signora.modules.signing.domain import Step


class Opened(BaseModel):
    recipient_id: uuid.UUID
    next: Step


class DisclosureParagraph(BaseModel):
    title: str
    text: str


class Disclosure(BaseModel):
    """The consumer disclosure for electronic records, as this person reads it (§3)."""

    version: str
    agreement: str  # the checkbox's words
    paragraphs: list[DisclosureParagraph]


class SignerState(BaseModel):
    recipient_id: uuid.UUID
    name: str
    email_masked: str
    title: str
    company: str
    sender_name: str
    sender_email: str
    next: Step
    signed_at: datetime | None
    disclosure: Disclosure


class CodeSentView(BaseModel):
    sent_at: datetime
    email_masked: str
    resend_after: int
