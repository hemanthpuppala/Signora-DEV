"""Random tokens and their stored forms (Phase 2 LLD NFR-A3, §4.3)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

TOKEN_BYTES = 32  # 256 bits


@dataclass(frozen=True)
class IssuedToken:
    """``value`` goes to the user once (link or cookie); only ``digest`` is stored."""

    value: str
    digest: bytes


def hash_token(value: str) -> bytes:
    """SHA-256 is enough: the input is 256 random bits, so it cannot be guessed or brute-forced."""
    return hashlib.sha256(value.encode("ascii", errors="replace")).digest()


def issue_token() -> IssuedToken:
    value = secrets.token_urlsafe(TOKEN_BYTES)
    return IssuedToken(value=value, digest=hash_token(value))


def csrf_token(secret_key: str, session_digest: bytes) -> str:
    """Signed double-submit token bound to one session; derived, never stored."""
    mac = hmac.new(secret_key.encode(), b"csrf:" + session_digest, hashlib.sha256)
    return mac.hexdigest()


def csrf_matches(secret_key: str, session_digest: bytes, presented: str | None) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(csrf_token(secret_key, session_digest), presented)
