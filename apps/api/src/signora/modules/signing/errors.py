"""Signing's refusals (Phase 8 LLD). Titles are what people read."""

from __future__ import annotations

from signora.kernel.errors import (
    Conflict,
    DomainError,
    NotFound,
    PermissionDenied,
    RetryAfter,
    Unauthenticated,
)


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


class VerifyFirst(PermissionDenied):
    code = "verify-first"
    title = "Enter the code from your email first"


class DisclosureChanged(Conflict):
    code = "disclosure-changed"
    title = "The terms for electronic records changed. Read them again to continue"


class ConsentFirst(PermissionDenied):
    code = "consent-first"
    title = "Agree to use electronic records first"


class AlreadySigned(Conflict):
    code = "already-signed"
    title = "You have already signed this"


class NotYours(PermissionDenied):
    code = "not-yours"
    title = "Someone else fills this field"


class FieldLocked(Conflict):
    code = "field-locked"
    title = "This was filled in before it was sent to you"


class FieldNotAsked(Conflict):
    code = "field-not-asked"
    title = "This field isn't asked with your other answers"
