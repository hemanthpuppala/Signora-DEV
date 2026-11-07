"""Log-in with throttling (Phase 2 LLD topic 7).

Unknown email and wrong password give the same error after the same amount of work. Per email,
waits start after the free attempts and double to a cap; per IP, failures are counted in a window.
A throttled attempt is refused before the password is checked, so a correct password waits too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from signora.kernel.config import AuthSettings
from signora.kernel.db import UnitOfWork
from signora.kernel.errors import RateLimited
from signora.kernel.logging import get_logger
from signora.kernel.ratelimit import RateLimiter
from signora.modules.identity_access import accounts
from signora.modules.identity_access.domain.emails import (
    InvalidEmailError,
    email_domain,
    normalize_email,
)
from signora.modules.identity_access.domain.passwords import (
    hash_password,
    spend_verification_time,
    verify_password,
)
from signora.modules.identity_access.domain.tokens import IssuedToken
from signora.modules.identity_access.errors import AccessRemoved, InvalidCredentials
from signora.modules.identity_access.sessions import create_session

security = get_logger("signora.security")

BACKOFF_BASE = timedelta(seconds=1)


@dataclass(frozen=True)
class LoginResult:
    token: IssuedToken
    user_id: str


def email_key(email: str) -> str:
    return f"login:email:{email}"


def ip_key(ip: str) -> str:
    return f"login:ip:{ip}"


def login(
    uow: UnitOfWork,
    *,
    limiter: RateLimiter,
    settings: AuthSettings,
    email: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
) -> LoginResult:
    try:
        normalized = normalize_email(email)
    except InvalidEmailError:
        normalized = email.strip().lower()[:254]  # still throttled and timed like any attempt
    ip_window = timedelta(minutes=settings.login_ip_window_minutes)

    retry = limiter.backoff(email_key(normalized))
    if retry is None and ip is not None:
        retry = limiter.check(ip_key(ip), limit=settings.login_ip_limit, window=ip_window)
    if retry is not None:
        security.warning("auth.login_throttled", email_domain=email_domain(normalized))
        raise RateLimited(retry)

    def fail(reason: str) -> InvalidCredentials:
        limiter.record_failure(
            email_key(normalized),
            free=settings.login_free_attempts,
            base=BACKOFF_BASE,
            cap=timedelta(minutes=settings.login_backoff_cap_minutes),
        )
        if ip is not None:
            limiter.hit(ip_key(ip), limit=settings.login_ip_limit, window=ip_window)
        security.warning("auth.login_failed", reason=reason, email_domain=email_domain(normalized))
        return InvalidCredentials()

    user = accounts.find_user_by_email(uow.session, normalized)
    if user is None:
        spend_verification_time(password)
        raise fail("unknown_email")
    verification = verify_password(user.password_hash, password)
    if not verification.ok:
        raise fail("wrong_password")
    if not user.active:
        security.warning("auth.login_refused_removed", user_id=str(user.id))
        raise AccessRemoved(
            f"You no longer have access to {user.workspace_name}. "
            "Ask the workspace owner if you need it back."
        )

    limiter.reset(email_key(normalized))
    if verification.needs_rehash:
        accounts.upgrade_password_hash(uow.session, user.id, hash_password(password))
    accounts.record_login(uow.session, user.id)
    token = create_session(uow.session, user.id, ip=ip, user_agent=user_agent)
    security.info("auth.login_succeeded", user_id=str(user.id), workspace_id=str(user.workspace_id))
    return LoginResult(token=token, user_id=str(user.id))
