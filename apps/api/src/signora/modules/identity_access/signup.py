"""Email-first sign-up (Phase 2 LLD topic 1, ADR-A2).

The request only rate-limits and enqueues; the job looks the address up and chooses the email, so
the response never depends on whether the address has an account, not even in timing.
"""

from __future__ import annotations

from datetime import timedelta

from signora.kernel.config import AuthSettings
from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, ValidationFailed
from signora.kernel.jobs import JobContext, enqueue
from signora.kernel.logging import get_logger
from signora.kernel.ratelimit import RateLimiter
from signora.modules.identity_access import accounts, company_logo, emails, links
from signora.modules.identity_access.domain.emails import (
    InvalidEmailError,
    email_domain,
    normalize_email,
)
from signora.modules.identity_access.domain.passwords import PasswordPolicy, hash_password
from signora.modules.identity_access.domain.website import InvalidWebsiteError, company_domain
from signora.modules.identity_access.errors import AccountExists
from signora.modules.notifications import send_email

SIGNUP_REQUEST = "identity.signup_request"

log = get_logger("signora.identity")


def valid_email(raw: str, field: str = "email") -> str:
    try:
        return normalize_email(raw)
    except InvalidEmailError as error:
        raise ValidationFailed([FieldError(field, str(error))]) from None


def valid_website(raw: str | None, field: str = "website") -> str | None:
    """The website's domain; ``None`` when none was given (the field is optional)."""
    if raw is None or not raw.strip():
        return None
    try:
        return company_domain(raw)
    except InvalidWebsiteError as error:
        raise ValidationFailed([FieldError(field, str(error))]) from None


def check_password(policy: PasswordPolicy, password: str, field: str = "password") -> None:
    problem = policy.problem(password)
    if problem is not None:
        raise ValidationFailed([FieldError(field, problem)])


def request_signup(
    uow: UnitOfWork,
    *,
    limiter: RateLimiter,
    settings: AuthSettings,
    email: str,
    ip: str | None,
) -> None:
    """Always succeeds for a well-formed address (``202`` to the caller)."""
    address = valid_email(email)
    if not links.link_email_allowed(limiter, settings, purpose="signup", email=address, ip=ip):
        log.info("signup.throttled", email_domain=email_domain(address))
        return
    enqueue(uow.session, SIGNUP_REQUEST, {"email": address})


def handle_signup_request(context: JobContext, *, base_url: str, settings: AuthSettings) -> None:
    """Send the verification link, or "you already have an account" to a registered address."""
    address: str = context.payload["email"]
    with context.complete() as uow:
        if accounts.find_user_by_email(uow.session, address) is not None:
            message = emails.already_registered(base_url)
        else:
            hours = settings.signup_link_hours
            token = links.issue_link(
                uow.session,
                purpose="signup",
                email=address,
                user_id=None,
                ttl=timedelta(hours=hours),
            )
            message = emails.verify_signup(base_url, token.value, hours)
        send_email(
            uow,
            to=address,
            subject=message.subject,
            text=message.body.text,
            html=message.body.html,
            category=message.category,
        )


def verify_signup(uow: UnitOfWork, token: str) -> str:
    """The address a live sign-up link belongs to."""
    return links.live_link(uow.session, purpose="signup", token=token).email


def complete_signup(
    uow: UnitOfWork,
    *,
    policy: PasswordPolicy,
    token: str,
    workspace_name: str,
    website: str | None,
    name: str,
    password: str,
    queue_logo_lookup: bool,
) -> str:
    """Create the workspace and its creator; returns the email. No session here: the page logs in
    next (LLD §1.2). A website plans the look-up of the company's logo, queued now when logos are
    configured; it never holds the sign-up up."""
    domain = valid_website(website)
    # Lock order: the address first, then the link. Completing marks every link of the address
    # used, so taking a link's row lock before the address lock would deadlock two completions.
    accounts.lock_email(
        uow.session, links.live_link(uow.session, purpose="signup", token=token).email
    )
    link = links.live_link(uow.session, purpose="signup", token=token, lock=True)
    if accounts.find_user_by_email(uow.session, link.email) is not None:
        raise AccountExists
    check_password(policy, password)
    created = accounts.create_workspace(
        uow,
        workspace_name=workspace_name,
        website=domain,
        creator_name=name,
        email=link.email,
        password_hash=hash_password(password),
    )
    links.use_up_links(uow.session, purpose="signup", email=link.email)
    if domain is not None:
        company_logo.plan_check(uow.session, created.workspace_id, queue=queue_logo_lookup)
    return link.email
