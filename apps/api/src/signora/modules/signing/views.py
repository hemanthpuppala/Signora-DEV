"""What the signer's page reads (Phase 8 LLD §1.5)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from signora.modules.signing.domain import Step


class Opened(BaseModel):
    recipient_id: uuid.UUID
    next: Step


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
