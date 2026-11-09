"""What a value of each field type may be (Phase 7 LLD §11.3)."""

from __future__ import annotations

import pytest

from signora.modules.identity_access import normalize_email
from signora.modules.review.formats import InvalidValueError, check_value
from signora.modules.review.values import MANUAL_HOLDS


def check(holds: str, raw: str, options: tuple[str, ...] = ()) -> str:
    return check_value(holds, raw, options=options, normalize_email=normalize_email)


@pytest.mark.parametrize(
    ("holds", "raw", "stored"),
    [
        ("text", "  Northwind Ltd  ", "Northwind Ltd"),
        ("email", " Maya.Chen@Example.COM ", "maya.chen@example.com"),
        ("phone", "+1 (415) 555-0100", "+1 (415) 555-0100"),
        ("date", "2026-11-09", "2026-11-09"),
        ("date_of_birth", "1990-02-28", "1990-02-28"),
        ("currency", "12,500.50", "12500.50"),
        ("number", "100", "100"),
        ("percent", "12.5%", "12.5"),
        ("checkbox", "true", "true"),
        ("choice", "Gold", "Gold"),
        ("url", "https://example.com/terms", "https://example.com/terms"),
        ("state", "Delaware", "Delaware"),
        ("other", "Matter 42", "Matter 42"),
    ],
)
def test_each_type_takes_its_values(holds: str, raw: str, stored: str) -> None:
    assert check(holds, raw, ("Gold", "Silver")) == stored


@pytest.mark.parametrize(
    ("holds", "raw", "message"),
    [
        ("text", "   ", "Enter a value"),
        ("text", "x" * 2001, "Use 2000 or fewer characters"),
        ("email", "not an email", "Enter a valid email address"),
        ("phone", "call me", "Enter a phone number"),
        ("date", "09/11/2026", "Enter a date"),
        ("number", "twelve", "Enter a number"),
        ("number", "NaN", "Enter a number"),
        ("percent", "120", "Enter a percentage from 0 to 100"),
        ("checkbox", "yes", "Tick it or leave it"),
        ("choice", "Bronze", "Choose one of the options"),
        ("url", "http://example.com", "Enter a web address starting with https://"),
        ("signature", "Maya", "This is given when signing"),
        ("date_signed", "2026-11-09", "This is given when signing"),
        ("hologram", "x", "This field's type is unknown"),
    ],
)
def test_a_value_its_field_cannot_hold_is_refused_in_plain_words(
    holds: str, raw: str, message: str
) -> None:
    with pytest.raises(InvalidValueError, match=message):
        check(holds, raw, ("Gold", "Silver"))


def test_every_type_is_judged() -> None:
    """Every type a person can choose in review is either typed (checked here) or signed."""
    for holds in MANUAL_HOLDS:
        try:
            check(holds, "x")
        except InvalidValueError as error:
            assert str(error) != "This field's type is unknown", holds
