"""What a value of each field type may be (Phase 7 LLD §11.3). Pure: no database.

One judge for a value given before signing (the sender, Phase 7) and while signing (the signer,
Phase 8), so a value is checked once, the same way, wherever it is typed. Signatures, initials and
signing dates are not values typed into a form: they are refused here (Phase 8 records them).

Emails are normalised by the caller's ``normalize_email`` (identity's, passed in), so "the same
email" keeps one definition.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from datetime import date
from decimal import Decimal, InvalidOperation

from signora.modules.review.values import MANUAL_HOLDS

TEXT_MAX = 2000
NOT_TYPED = frozenset({"signature", "initials", "date_signed"})  # given by signing (Phase 8)
_NUMBERS = frozenset({"number", "currency", "percent"})
_PHONE = re.compile(r"^\+?[0-9 ().-]{7,30}$")
_URL = re.compile(r"^https://[^\s/$.?#][^\s]*$", re.IGNORECASE)


class InvalidValueError(ValueError):
    """A value its field cannot hold; the message says what to type, in plain words."""


def check_value(
    holds: str,
    raw: str,
    *,
    options: Collection[str] = (),
    normalize_email: Callable[[str], str],
) -> str:
    """The value as stored, or ``InvalidValueError``. ``options`` are a choice's option values."""
    if holds not in MANUAL_HOLDS:
        raise InvalidValueError("This field's type is unknown")
    if holds in NOT_TYPED:
        raise InvalidValueError("This is given when signing")
    value = raw.strip()
    if not value:
        raise InvalidValueError("Enter a value")
    if len(value) > TEXT_MAX:
        raise InvalidValueError(f"Use {TEXT_MAX} or fewer characters")
    if holds == "email":
        try:
            return normalize_email(value)
        except ValueError:
            raise InvalidValueError("Enter a valid email address") from None
    if holds == "phone":
        if not _PHONE.match(value) or sum(ch.isdigit() for ch in value) < 7:
            raise InvalidValueError("Enter a phone number")
        return value
    if holds in ("date", "date_of_birth"):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise InvalidValueError("Enter a date") from None
    if holds in _NUMBERS:
        try:
            number = Decimal(value.replace(",", "").removesuffix("%").strip())
        except InvalidOperation:
            raise InvalidValueError("Enter a number") from None
        if not number.is_finite():
            raise InvalidValueError("Enter a number")
        if holds == "percent" and not Decimal(0) <= number <= Decimal(100):
            raise InvalidValueError("Enter a percentage from 0 to 100")
        whole = number == number.to_integral_value()
        return str(number.quantize(Decimal(1))) if whole else str(number)  # "100", not "1E+2"
    if holds == "checkbox":
        if value not in ("true", "false"):
            raise InvalidValueError("Tick it or leave it")
        return value
    if holds == "choice":
        if value not in options:
            raise InvalidValueError("Choose one of the options")
        return value
    if holds == "url":
        if not _URL.match(value):
            raise InvalidValueError("Enter a web address starting with https://")
        return value
    return value  # text, names, addresses, tax and bank numbers, notes, other
