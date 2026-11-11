"""The email code (Phase 8 LLD §2): six digits, single use, ten minutes, five wrong tries.

Only ``HMAC-SHA256(code_key, recipient ‖ link version ‖ code)`` is kept, with a key derived from the
application secret for this one purpose, so a copy of the database cannot be tried against the
million codes. A person has at most one live code; its row's lock orders a try and a new code.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Row, text

from signora.kernel.config import get_settings
from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, ValidationFailed
from signora.modules.envelopes import SignerRecipient, moment_in_words
from signora.modules.notifications import render_layout, send_email
from signora.modules.signing.domain import mask_email
from signora.modules.signing.errors import CodeEnded, CodeLimit, CodeNotRequired, CodeWait
from signora.modules.signing.trail import audit

PURPOSE = b"signora signing code v1"
RESEND_AFTER = timedelta(seconds=60)
WINDOW = timedelta(hours=1)
PER_WINDOW = 5


def code_key(secret_key: str) -> bytes:
    return hmac.new(secret_key.encode(), PURPOSE, hashlib.sha256).digest()


def code_mac(key: bytes, recipient_id: uuid.UUID, link_version: int, code: str) -> bytes:
    payload = recipient_id.bytes + link_version.to_bytes(4, "big") + code.encode("ascii")
    return hmac.new(key, payload, hashlib.sha256).digest()


def _key() -> bytes:
    return code_key(get_settings().app.secret_key.get_secret_value())


@dataclass(frozen=True)
class CodeSent:
    sent_at: datetime
    email_masked: str
    resend_after: int  # seconds until a new code may be asked for


def _seconds(span: timedelta) -> int:
    return max(0, math.ceil(span.total_seconds()))


def _row(uow: UnitOfWork, recipient_id: uuid.UUID) -> Row[Any] | None:
    return uow.session.execute(
        text(
            "SELECT link_version, code_mac, sent_at, expires_at, wrong_tries, used_at, "
            "window_start, sent_in_window, now() AS now "
            "FROM signing_codes WHERE recipient_id = :r FOR UPDATE"
        ),
        {"r": recipient_id},
    ).one_or_none()


def _now(uow: UnitOfWork) -> datetime:
    now: datetime = uow.session.execute(text("SELECT now()")).scalar_one()
    return now


def _live(row: Row[Any] | None, recipient: SignerRecipient, now: datetime) -> bool:
    limit = get_settings().signing.otp_max_attempts
    return (
        row is not None
        and row.link_version == recipient.link_version
        and row.used_at is None
        and row.expires_at > now
        and row.wrong_tries < limit
    )


def send_code(uow: UnitOfWork, recipient: SignerRecipient, *, again: bool) -> CodeSent:
    """Send a code, or keep the live one when the person did not ask for a new one (§2.1.1)."""
    if not recipient.require_email_code or recipient.kind == "countersigner":
        raise CodeNotRequired  # a countersigner's sign-in is their proof (§7.1.2)
    row = _row(uow, recipient.id)
    now = row.now if row is not None else _now(uow)
    if row is not None and row.link_version != recipient.link_version:
        # A corrected email: the wait and the hourly count were the old address's, not this one's.
        row = None
    masked = mask_email(recipient.email)
    if row is not None and _live(row, recipient, now) and not again:
        return CodeSent(row.sent_at, masked, _seconds(row.sent_at + RESEND_AFTER - now))
    if row is not None and now < row.sent_at + RESEND_AFTER:
        raise CodeWait(_seconds(row.sent_at + RESEND_AFTER - now))
    if row is not None and now < row.window_start + WINDOW:
        window_start, count = row.window_start, row.sent_in_window + 1
    else:
        window_start, count = now, 1
    if count > PER_WINDOW:
        raise CodeLimit(_seconds(window_start + WINDOW - now))

    code = f"{secrets.randbelow(10**6):06d}"
    expires_at = now + timedelta(minutes=get_settings().signing.otp_ttl_minutes)
    uow.session.execute(
        text(
            """
            INSERT INTO signing_codes (recipient_id, workspace_id, link_version, code_mac, sent_at,
                                       expires_at, window_start, sent_in_window)
            VALUES (:r, :w, :v, :mac, :now, :exp, :ws, :n)
            ON CONFLICT (recipient_id) DO UPDATE
            SET link_version = EXCLUDED.link_version, code_mac = EXCLUDED.code_mac,
                sent_at = EXCLUDED.sent_at, expires_at = EXCLUDED.expires_at, wrong_tries = 0,
                used_at = NULL, window_start = EXCLUDED.window_start,
                sent_in_window = EXCLUDED.sent_in_window
            """
        ),
        {
            "r": recipient.id,
            "w": recipient.workspace_id,
            "v": recipient.link_version,
            "mac": code_mac(_key(), recipient.id, recipient.link_version, code),
            "now": now,
            "exp": expires_at,
            "ws": window_start,
            "n": count,
        },
    )
    _email(uow, recipient, code, expires_at, dedupe=f"{window_start.isoformat()}:{count}")
    audit(uow, recipient, "signing.code_sent")
    return CodeSent(now, masked, _seconds(RESEND_AFTER))


def _email(
    uow: UnitOfWork, recipient: SignerRecipient, code: str, expires_at: datetime, *, dedupe: str
) -> None:
    until = moment_in_words(expires_at.astimezone(ZoneInfo(recipient.time_zone)))
    body = render_layout(
        heading=f"Your code is {code}",
        paragraphs=[
            f"Enter it on the signing page to open {recipient.title}. It works until {until}.",
        ],
        footer="If you didn't ask for this, you can ignore it.",
    )
    send_email(
        uow,
        to=recipient.email,
        subject=f"{code} is your code for {recipient.title}",
        text=body.text,
        html=body.html,
        category="sign_code",
        workspace_id=recipient.workspace_id,
        dedupe_key=f"sign_code:{recipient.id}:{dedupe}",
    )


@dataclass(frozen=True)
class Tried:
    """A try's outcome: verified, or how many tries are left (0: the code has ended)."""

    verified: bool
    tries_left: int


def try_code(uow: UnitOfWork, recipient: SignerRecipient, code: str) -> Tried:
    """Check a code under its row's lock (§2.4). A wrong try is counted by the caller's commit."""
    row = _row(uow, recipient.id)
    if row is None or not _live(row, recipient, row.now):
        raise CodeEnded
    presented = code_mac(_key(), recipient.id, recipient.link_version, code)
    if hmac.compare_digest(presented, bytes(row.code_mac)):
        uow.session.execute(
            text("UPDATE signing_codes SET used_at = now() WHERE recipient_id = :r"),
            {"r": recipient.id},
        )
        return Tried(verified=True, tries_left=0)
    tries = row.wrong_tries + 1
    uow.session.execute(
        text("UPDATE signing_codes SET wrong_tries = :t WHERE recipient_id = :r"),
        {"t": tries, "r": recipient.id},
    )
    return Tried(verified=False, tries_left=get_settings().signing.otp_max_attempts - tries)


def wrong_code(tries_left: int) -> ValidationFailed:
    if tries_left == 0:
        message = "That code isn't right. Ask for a new code."
    else:
        message = (
            f"That code isn't right. {tries_left} {'try' if tries_left == 1 else 'tries'} left."
        )
    return ValidationFailed([FieldError("code", message)], detail=message)
