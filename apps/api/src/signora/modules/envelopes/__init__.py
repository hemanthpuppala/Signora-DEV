"""Envelopes module: sending one approved version to its parties (Phase 7 LLD).

Public interface — other modules import only from here.
"""

from signora.modules.envelopes.recipients import (
    SignerRecipient,
    recipient_for_signing,
    record_opened,
)
from signora.modules.envelopes.routes import router
from signora.modules.envelopes.store import count_sends

__all__ = [
    "SignerRecipient",
    "count_sends",
    "recipient_for_signing",
    "record_opened",
    "router",
]
