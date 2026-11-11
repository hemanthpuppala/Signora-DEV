"""Domain errors (backbone LLD §7.1).

Modules raise these; one handler in the HTTP layer turns them into RFC 9457 problem details. This
module has no web-framework dependency, so domain code can raise errors without knowing about HTTP.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class FieldError:
    """One invalid input field, e.g. ``FieldError("poc_emails[0]", "Not a valid email")``."""

    field: str
    message: str


class DomainError(Exception):
    """Base class. Subclasses set a stable ``code``, an HTTP ``status`` and a human ``title``."""

    code: ClassVar[str] = "error"
    status: ClassVar[int] = 400
    title: ClassVar[str] = "The request could not be completed"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(detail or self.title)

    @property
    def headers(self) -> Mapping[str, str]:
        return {}

    @property
    def field_errors(self) -> Sequence[FieldError]:
        return ()


class ValidationFailed(DomainError):
    code = "validation-failed"
    status = 422
    title = "Some fields are invalid"

    def __init__(self, errors: Sequence[FieldError], detail: str | None = None) -> None:
        self._errors = tuple(errors)
        count = len(self._errors)
        noun = "field needs" if count == 1 else "fields need"
        super().__init__(detail or f"{count} {noun} attention")

    @property
    def field_errors(self) -> Sequence[FieldError]:
        return self._errors


class Unauthenticated(DomainError):
    code = "unauthenticated"
    status = 401
    title = "Please sign in"


class PermissionDenied(DomainError):
    code = "permission-denied"
    status = 403
    title = "You do not have access to this"


class NotFound(DomainError):
    """Also used for resources of another workspace, so their existence is never revealed."""

    code = "not-found"
    status = 404
    title = "Not found"


class Conflict(DomainError):
    code = "conflict"
    status = 409
    title = "This action does not fit the current state"


class RetryAfter(DomainError):
    def __init__(self, retry_after_seconds: int, detail: str | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail)

    @property
    def headers(self) -> Mapping[str, str]:
        return {"Retry-After": str(self.retry_after_seconds)}


class IdempotencyKeyMissing(DomainError):
    code = "idempotency-key-missing"
    status = 400
    title = "An Idempotency-Key header is required for this request"


class IdempotencyKeyInvalid(DomainError):
    code = "idempotency-key-invalid"
    status = 400
    title = "The Idempotency-Key header must be 1-255 printable characters"


class IdempotencyKeyReused(DomainError):
    code = "idempotency-key-reused"
    status = 422
    title = "This Idempotency-Key was already used for a different request"


class RequestInProgress(RetryAfter):
    code = "request-in-progress"
    status = 409
    title = "A request is outstanding for this Idempotency-Key"


class PayloadTooLarge(DomainError):
    code = "payload-too-large"
    status = 413
    title = "The upload is too large"


class RateLimited(RetryAfter):
    code = "rate-limited"
    status = 429
    title = "Too many attempts; try again later"


class IntegrationNotConfigured(DomainError):
    code = "integration-not-configured"
    status = 503
    title = "This feature is not configured"
