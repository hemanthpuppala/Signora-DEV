"""One-time email links for sign-up and password reset (Phase 2 LLD topics 1-2).

A link token is stored only as its SHA-256. Unknown, used and expired tokens are indistinguishable
to the caller (``LinkExpired``). Requests that send a link email are rate limited per address and
per IP without revealing whether the address has an account.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.config import AuthSettings
from signora.kernel.ratelimit import RateLimiter
from signora.modules.identity_access.domain.tokens import IssuedToken, hash_token, issue_token
from signora.modules.identity_access.errors import LinkExpired

Purpose = Literal["signup", "password_reset"]


def issue_link(
    session: Session,
    *,
    purpose: Purpose,
    email: str,
    user_id: uuid.UUID | None,
    ttl: timedelta,
) -> IssuedToken:
    token = issue_token()
    session.execute(
        text(
            "INSERT INTO email_tokens (purpose, email, user_id, token_hash, expires_at) "
            "VALUES (:p, :e, :u, :h, now() + make_interval(secs => :ttl))"
        ),
        {"p": purpose, "e": email, "u": user_id, "h": token.digest, "ttl": ttl.total_seconds()},
    )
    return token


@dataclass(frozen=True)
class LiveLink:
    email: str
    user_id: uuid.UUID | None


def live_link(session: Session, *, purpose: Purpose, token: str, lock: bool = False) -> LiveLink:
    """The unused, unexpired link for ``token``; ``lock`` holds it until the transaction ends so
    two completions with one link cannot both succeed."""
    query = (
        "SELECT email, user_id FROM email_tokens WHERE token_hash = :h AND purpose = :p "
        "AND used_at IS NULL AND expires_at > now()"
    )
    row = session.execute(
        text(query + (" FOR UPDATE" if lock else "")), {"h": hash_token(token), "p": purpose}
    ).one_or_none()
    if row is None:
        raise LinkExpired
    return LiveLink(row.email, row.user_id)


def use_up_links(session: Session, *, purpose: Purpose, email: str) -> None:
    """Every unused link of this purpose for the address stops working."""
    session.execute(
        text(
            "UPDATE email_tokens SET used_at = now() "
            "WHERE purpose = :p AND email = :e AND used_at IS NULL"
        ),
        {"p": purpose, "e": email},
    )


def link_email_allowed(
    limiter: RateLimiter, settings: AuthSettings, *, purpose: Purpose, email: str, ip: str | None
) -> bool:
    """Whether a link email may be sent now: a cooldown and an hourly cap per address, and the
    log-in IP limit per IP. Callers answer the same way either way."""
    checks = [
        (
            f"email:{purpose}:cooldown:{email}",
            1,
            timedelta(seconds=settings.email_cooldown_seconds),
        ),
        (f"email:{purpose}:hour:{email}", settings.email_hourly_limit, timedelta(hours=1)),
    ]
    if ip is not None:
        checks.append(
            (
                f"email:ip:{ip}",
                settings.login_ip_limit,
                timedelta(minutes=settings.login_ip_window_minutes),
            )
        )
    if any(limiter.check(key, limit=limit, window=window) for key, limit, window in checks):
        return False
    for key, limit, window in checks:
        limiter.hit(key, limit=limit, window=window)
    return True
