"""Password reset and password change (Phase 2 LLD topic 2, §8.2)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import text

from signora.kernel.config import AuthSettings
from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, RateLimited, ValidationFailed
from signora.kernel.jobs import JobContext, enqueue
from signora.kernel.logging import get_logger
from signora.kernel.ratelimit import RateLimiter
from signora.modules.identity_access import accounts, emails, links
from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.domain.emails import email_domain
from signora.modules.identity_access.domain.passwords import (
    PasswordPolicy,
    hash_password,
    verify_password,
)
from signora.modules.identity_access.errors import LinkExpired
from signora.modules.identity_access.sessions import delete_user_sessions
from signora.modules.identity_access.signup import check_password, valid_email
from signora.modules.notifications import send_email

RESET_REQUEST = "identity.password_reset_request"

log = get_logger("signora.identity")
security = get_logger("signora.security")


def _send(uow: UnitOfWork, to: str, message: emails.AccountEmail) -> None:
    send_email(
        uow,
        to=to,
        subject=message.subject,
        text=message.body.text,
        html=message.body.html,
        category=message.category,
    )


def request_reset(
    uow: UnitOfWork, *, limiter: RateLimiter, settings: AuthSettings, email: str, ip: str | None
) -> None:
    """Always succeeds for a well-formed address (``202``); the job decides whether to send."""
    address = valid_email(email)
    if not links.link_email_allowed(
        limiter, settings, purpose="password_reset", email=address, ip=ip
    ):
        log.info("password_reset.throttled", email_domain=email_domain(address))
        return
    enqueue(uow.session, RESET_REQUEST, {"email": address})


def handle_reset_request(context: JobContext, *, base_url: str, settings: AuthSettings) -> None:
    """Send a reset link to an active user; nothing to unknown or removed addresses (OWASP)."""
    address: str = context.payload["email"]
    with context.complete() as uow:
        user = accounts.find_user_by_email(uow.session, address)
        if user is None or not user.active:
            return
        minutes = settings.reset_link_minutes
        token = links.issue_link(
            uow.session,
            purpose="password_reset",
            email=address,
            user_id=user.id,
            ttl=timedelta(minutes=minutes),
        )
        _send(uow, address, emails.reset_password(base_url, token.value, minutes))


def verify_reset(uow: UnitOfWork, token: str) -> str:
    return links.live_link(uow.session, purpose="password_reset", token=token).email


def complete_reset(
    uow: UnitOfWork, *, policy: PasswordPolicy, token: str, password: str, base_url: str
) -> str:
    """Set the new password, use up the user's reset links, end every session; returns the email."""
    link = links.live_link(uow.session, purpose="password_reset", token=token, lock=True)
    user = accounts.find_user_by_email(uow.session, link.email)
    if user is None or not user.active or user.id != link.user_id:
        raise LinkExpired
    check_password(policy, password)
    accounts.set_password(uow.session, user.id, hash_password(password))
    links.use_up_links(uow.session, purpose="password_reset", email=link.email)
    ended = delete_user_sessions(uow.session, user.id)
    _send(uow, link.email, emails.password_changed(base_url))
    security.info("auth.password_reset", user_id=str(user.id), sessions_ended=ended)
    return link.email


def _current_hash(uow: UnitOfWork, user_id: uuid.UUID) -> str:
    stored: str = uow.session.execute(
        text("SELECT password_hash FROM users WHERE id = :u"), {"u": user_id}
    ).scalar_one()
    return stored


def change_password(
    uow: UnitOfWork,
    *,
    actor: Actor,
    limiter: RateLimiter,
    settings: AuthSettings,
    current_password: str,
    new_password: str,
    base_url: str,
) -> None:
    """Needs the current password (so an unlocked computer is not enough); ends the user's other
    sessions; wrong guesses are throttled like log-ins."""
    key = f"password-change:{actor.user_id}"
    retry = limiter.backoff(key)
    if retry is not None:
        raise RateLimited(retry)
    if not verify_password(_current_hash(uow, actor.user_id), current_password).ok:
        limiter.record_failure(
            key,
            free=settings.login_free_attempts,
            base=timedelta(seconds=1),
            cap=timedelta(minutes=settings.login_backoff_cap_minutes),
        )
        raise ValidationFailed(
            [FieldError("current_password", "This is not your current password")]
        )
    limiter.reset(key)
    check_password(PasswordPolicy(settings.password_min_length), new_password, "new_password")
    accounts.set_password(uow.session, actor.user_id, hash_password(new_password))
    ended = delete_user_sessions(uow.session, actor.user_id, keep=actor.session_digest)
    _send(uow, actor.email, emails.password_changed(base_url))
    security.info("auth.password_changed", user_id=str(actor.user_id), sessions_ended=ended)
