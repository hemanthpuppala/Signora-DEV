"""Email normalisation: the one definition of "the same email" (Phase 2 LLD §8.3)."""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email

MAX_EMAIL_LENGTH = 254


class InvalidEmailError(ValueError):
    pass


def normalize_email(raw: str) -> str:
    """Trim, check syntax and lowercase the whole address. Dots and ``+tags`` are kept as typed.

    Raises ``InvalidEmailError`` for anything that is not a single valid address.
    """
    candidate = raw.strip()
    if not candidate or len(candidate) > MAX_EMAIL_LENGTH:
        raise InvalidEmailError("Enter a valid email address")
    try:
        validated = validate_email(candidate, check_deliverability=False)
    except EmailNotValidError:
        raise InvalidEmailError("Enter a valid email address") from None
    return validated.normalized.lower()


def email_domain(email: str) -> str:
    """The part after ``@`` (logged instead of the full address)."""
    return email.rsplit("@", 1)[-1]
