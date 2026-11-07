"""Audit module: append-only, hash-chained record of who did what (backbone LLD topic 4).

Public interface — other modules import only from here.
"""

from signora.modules.audit.domain import (
    SYSTEM_WORKSPACE_ID,
    Actor,
    AuditChain,
    AuditEntry,
    ChainKind,
    Subject,
    VerificationResult,
)
from signora.modules.audit.service import record, verify

__all__ = [
    "SYSTEM_WORKSPACE_ID",
    "Actor",
    "AuditChain",
    "AuditEntry",
    "ChainKind",
    "Subject",
    "VerificationResult",
    "record",
    "verify",
]
