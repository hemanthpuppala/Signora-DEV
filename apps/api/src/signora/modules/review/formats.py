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

from signora.modules.review.values import MANUAL_HOLDS

TEXT_MAX = 2000
NOT_TYPED = frozenset({"signature", "initials", "date_signed"})  # given by signing (Phase 8)
_NUMBERS = frozenset({"number", "currency", "percent"})
NUMBER_MAX_DIGITS = 28
# A number as people type one: a sign, digits (commas between them are grouping), a decimal point.
# ASCII digits only: no exponent, no other script's digits, nothing else a parser would let through.
_NUMBER = re.compile(r"(?P<sign>[+-]?)(?P<whole>[0-9][0-9,]*)?(?:\.(?P<part>[0-9]*))?", re.ASCII)
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
        return _number(holds, value)
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


def _number(holds: str, value: str) -> str:
    """A number kept canonical: digits without grouping or leading zeros, a decimal part only when
    it says something ("1,250,000.00" is "1250000"; "1.50" stays "1.50"), a minus only on a number
    that is not zero. A percentage may end in "%" and is from 0 to 100. Read from its text, never
    through arithmetic, so its length is the only limit: O(len(value)). The preview keeps the same
    rule (the web's ``typeset.kept``; both run packages/contracts/vectors/numbers.json)."""
    text = value.removesuffix("%").rstrip() if holds == "percent" else value
    match = _NUMBER.fullmatch(text)
    whole = (match["whole"] or "").replace(",", "") if match else ""
    part = (match["part"] or "") if match else ""
    if match is None or not whole + part:
        raise InvalidValueError("Enter a number")
    if len(whole + part) > NUMBER_MAX_DIGITS:
        raise InvalidValueError(f"Use {NUMBER_MAX_DIGITS} or fewer digits")
    whole = whole.lstrip("0") or "0"
    part = part if part.strip("0") else ""
    zero = whole == "0" and not part
    negative = match["sign"] == "-" and not zero
    if holds == "percent" and (
        negative or (len(whole), whole) > (3, "100") or (whole == "100" and part)
    ):
        raise InvalidValueError("Enter a percentage from 0 to 100")
    return ("-" if negative else "") + whole + (f".{part}" if part else "")


def _digits(value: str) -> bool:
    """Only the digits 0-9: ``str.isdigit`` alone also takes "²" and other scripts' digits, which
    ``int`` refuses or which would be printed as typed."""
    return value.isascii() and value.isdigit()


def _date_part(holds: str, value: str) -> str:
    """One part of a date split into boxes, kept canonical (Phase 7c): a day 1-31; a month as its
    number, given as a number or a name; a year in four digits, two read in today's century. How
    it is written on the page is its field's format (``written``)."""
    if holds == "month":
        if _digits(value):
            if not 1 <= int(value) <= 12:
                raise InvalidValueError("Enter a month")
            return str(int(value))
        named = [m for m in _MONTHS if len(value) >= 3 and m.lower().startswith(value.lower())]
        if len(named) != 1:
            raise InvalidValueError("Enter a month")
        return str(_MONTHS.index(named[0]) + 1)
    if holds == "day":
        if not _digits(value) or not 1 <= int(value) <= 31:
            raise InvalidValueError("Enter a day from 1 to 31")
        return str(int(value))
    if not _digits(value) or len(value) not in (2, 4):
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


def check_written(holds: str, value: str, chosen: str | None) -> None:
    """Whether a canonical value can be written in its field's format without saying something
    else; ``InvalidValueError`` when it cannot. A year written in two digits follows a printed
    century, today's (two digits typed are read in it too): a year of another century would print
    as a different year ("1999" after a printed "20" reads 2099)."""
    if holds != "year" or format_for(holds, chosen) != "YY":
        return
    century = datetime.now(UTC).year // 100
    if int(value) // 100 != century:
        raise InvalidValueError(f"Enter a year from {century}00 to {century}99")


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
