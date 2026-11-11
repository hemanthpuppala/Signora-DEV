"""What the signer's page reads (Phase 8 LLD §1.5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

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
    kind: Literal["signer", "countersigner"]
    name: str
    email_masked: str
    title: str
    document_name: str  # what the screen shows: the envelope's title may end in the signer's name
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


VerifiedBy = Literal["email_code", "email_link", "signora_sign_in"]


class DoneView(BaseModel):
    """The done screen (§9.1): when they signed, how they proved who they are, what is next."""

    signed_at: datetime
    verified_by: VerifiedBy
    waiting_for: list[str]  # signers still to sign
    countersigning: str | None  # the company, while its countersigners have still to sign
    completed: bool  # the signed copy is made: offered to a countersigner to download
    approved: bool  # they had nowhere to sign: they reviewed and approved
