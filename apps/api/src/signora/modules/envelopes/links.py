"""Signing links (Phase 7 LLD §11.2, ADR-E1). Pure: no database.

A link names its recipient and their link version, signed with an HMAC: it can be shown again
(Copy signing link, resend) by computing it again, nothing that rebuilds it is stored, and moving
the recipient's link version on revokes every earlier link. The key is derived from the
application's secret for this one purpose, so no second secret is kept.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import uuid
from dataclasses import dataclass

PURPOSE = b"signora signing link v1"
_ID = 16  # bytes of a UUID
_VERSION = 4  # bytes of the link version
_MAC = 32  # bytes of an HMAC-SHA256
TOKEN_BYTES = _ID + _VERSION + _MAC


def link_key(secret_key: str) -> bytes:
    """The key for signing links, derived from the application secret (32+ characters)."""
    return hmac.new(secret_key.encode(), PURPOSE, hashlib.sha256).digest()


def _mac(key: bytes, payload: bytes) -> bytes:
    return hmac.new(key, payload, hashlib.sha256).digest()


def make_token(key: bytes, recipient_id: uuid.UUID, link_version: int) -> str:
    """The token in a recipient's link: 70 URL-safe characters."""
    payload = recipient_id.bytes + link_version.to_bytes(_VERSION, "big")
    return base64.urlsafe_b64encode(payload + _mac(key, payload)).decode().rstrip("=")


@dataclass(frozen=True)
class LinkClaim:
    """Who a genuine token names; the caller still checks the version is current and not revoked."""

    recipient_id: uuid.UUID
    link_version: int


def read_token(key: bytes, token: str) -> LinkClaim | None:
    """The recipient a genuine token names, or ``None`` for anything else (compared in constant
    time, so a forged token learns nothing from how long it took to refuse)."""
    if len(token) > 128:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError):
        return None
    if len(raw) != TOKEN_BYTES:
        return None
    payload, mac = raw[: _ID + _VERSION], raw[_ID + _VERSION :]
    if not hmac.compare_digest(mac, _mac(key, payload)):
        return None
    return LinkClaim(uuid.UUID(bytes=payload[:_ID]), int.from_bytes(payload[_ID:], "big"))


def signing_url(public_base_url: str, token: str) -> str:
    return f"{public_base_url.rstrip('/')}/s/{token}"
