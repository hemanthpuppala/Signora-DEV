"""Signing's refusals (Phase 8 LLD). Titles are what people read."""

from __future__ import annotations

from signora.kernel.errors import Conflict, DomainError, NotFound, RetryAfter, Unauthenticated


class LinkClosed(NotFound):
    """One answer for every link that cannot be used, so a guess learns nothing (§1.1.6)."""

    code = "link-closed"
    title = "This request is no longer open. Nothing more is needed from you"


class SessionEnded(Unauthenticated):
    code = "session-ended"
    title = "Your session ended. Open the link in your email again"


class CodeWait(RetryAfter):
    code = "code-wait"
    status = 429
    title = "A new code can be sent in a minute"


class CodeLimit(RetryAfter):
    code = "code-limit"
    status = 429
    title = "Too many codes. Try again later"


class CodeEnded(DomainError):
    """Expired, used, or ended by too many wrong tries: a new code is needed."""

    code = "code-ended"
    status = 410
    title = "That code has ended. Ask for a new one"


class CodeNotRequired(Conflict):
    code = "code-not-required"
    title = "This envelope does not ask for an email code"
