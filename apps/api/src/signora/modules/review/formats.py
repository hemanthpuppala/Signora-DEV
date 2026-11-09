"""What a value of each field type may be (Phase 7 LLD §11.3), and how a date or a part of one is
written on the page (Phase 7c). Pure: no database.

One judge for a value given before signing (the sender, Phase 7) and while signing (the signer,
Phase 8), so a value is checked once, the same way, wherever it is typed. Signatures, initials and
signing dates are not values typed into a form: they are refused here (Phase 8 records them).

Emails are normalised by the caller's ``normalize_email`` (identity's, passed in), so "the same
email" keeps one definition.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from signora.modules.review.values import MANUAL_HOLDS

TEXT_MAX = 2000
NOT_TYPED = frozenset({"signature", "initials", "date_signed"})  # given by signing (Phase 8)
_NUMBERS = frozenset({"number", "currency", "percent"})
_PHONE = re.compile(r"^\+?[0-9 ().-]{7,30}$")
_URL = re.compile(r"^https://[^\s/$.?#][^\s]*$", re.IGNORECASE)


# The months by name: a month is given by its number or its name and kept as its number.
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


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
    if holds in ("day", "month", "year"):
        return _date_part(holds, value)
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


def _date_part(holds: str, value: str) -> str:
    """One part of a date split into boxes, kept canonical (Phase 7c): a day 1-31; a month as its
    number, given as a number or a name; a year in four digits, two read in today's century. How
    it is written on the page is its field's format (``written``)."""
    if holds == "month":
        if value.isdigit() and 1 <= int(value) <= 12:
            return str(int(value))
        named = [m for m in _MONTHS if len(value) >= 3 and m.lower().startswith(value.lower())]
        if len(named) != 1:
            raise InvalidValueError("Enter a month")
        return str(_MONTHS.index(named[0]) + 1)
    if holds == "day":
        if not value.isdigit() or not 1 <= int(value) <= 31:
            raise InvalidValueError("Enter a day from 1 to 31")
        return str(int(value))
    if not value.isdigit() or len(value) not in (2, 4):
        raise InvalidValueError("Enter a year, such as 2026")
    return value if len(value) == 4 else str(datetime.now(UTC).year // 100 * 100 + int(value))


# How a date, or a part of one, is written on the page (Phase 7c): per type, the default first.
_WHOLE_DATE = (
    "Month D, YYYY",
    "MM/DD/YYYY",
    "DD/MM/YYYY",
    "MM/DD/YY",
    "DD/MM/YY",
    "YYYY-MM-DD",
    "D Month YYYY",
)
FORMATS: dict[str, tuple[str, ...]] = {
    "date": _WHOLE_DATE,
    "date_signed": _WHOLE_DATE,
    "date_of_birth": _WHOLE_DATE,
    "day": ("D", "Dth"),
    "month": ("Month", "MM"),
    "year": ("YYYY", "YY"),
}
ALL_FORMATS: tuple[str, ...] = tuple(dict.fromkeys(f for fs in FORMATS.values() for f in fs))


def default_format(holds: str) -> str | None:
    """The type's first format, or None for a type that has none."""
    formats = FORMATS.get(holds)
    return formats[0] if formats else None


def format_for(holds: str, chosen: str | None) -> str | None:
    """The field's format: its own when the type has it, else the type's default."""
    formats = FORMATS.get(holds)
    if not formats:
        return None
    return chosen if chosen in formats else formats[0]


def _ordinal(day: int) -> str:
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def written(holds: str, value: str, chosen: str | None) -> str:
    """A canonical value as its field writes it (O(1)). A value of a type without formats, or one
    that is not canonical (stored before formats), is written as it is."""
    fmt = format_for(holds, chosen)
    if fmt is None:
        return value
    try:
        if holds in ("day",):
            day = int(value)
            return _ordinal(day) if fmt == "Dth" else str(day)
        if holds == "month":
            number = int(value) if value.isdigit() else _MONTHS.index(value.title()) + 1
            return _MONTHS[number - 1] if fmt == "Month" else f"{number:02d}"
        if holds == "year":
            return value[-2:] if fmt == "YY" else value
        when = date.fromisoformat(value)
    except (ValueError, IndexError):
        return value
    month = _MONTHS[when.month - 1]
    return {
        "Month D, YYYY": f"{month} {when.day}, {when.year}",
        "MM/DD/YYYY": f"{when.month:02d}/{when.day:02d}/{when.year}",
        "DD/MM/YYYY": f"{when.day:02d}/{when.month:02d}/{when.year}",
        "MM/DD/YY": f"{when.month:02d}/{when.day:02d}/{when.year % 100:02d}",
        "DD/MM/YY": f"{when.day:02d}/{when.month:02d}/{when.year % 100:02d}",
        "YYYY-MM-DD": when.isoformat(),
        "D Month YYYY": f"{when.day} {month} {when.year}",
    }[fmt]
