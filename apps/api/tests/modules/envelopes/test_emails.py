"""What the signer receives (Phase 7 LLD §5): the words, one button, the link printed under it."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from signora.modules.envelopes.emails import Letter, sign_reminder, sign_request, sign_withdrawn

URL = "https://signora.example/s/abc123"
EXPIRES = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def test_the_request_names_who_asks_what_and_until_when() -> None:
    letter = sign_request(
        company="Hale & Ward LLP",
        sender="Rosa Hale",
        signer="Maya Chen",
        document="Mutual NDA",
        url=URL,
        expires_at=EXPIRES,
    )

    assert letter.subject == "Hale & Ward LLP asks you to sign Mutual NDA"
    text = letter.body.text
    assert "Hi Maya, Rosa Hale sent you this to review and sign." in text
    assert f"Review and sign: {URL}" in text
    assert "It expires on Nov 23, 2026 at 12:00 PM UTC. Questions? Reply to this email." in text
    html = letter.body.html
    assert html.count(URL) == 2  # the button, and printed under it to copy (emails run no scripts)
    assert "Hale &amp; Ward LLP" in html  # escaped: the company's name is text, never HTML


def test_the_reminder_and_the_withdrawal() -> None:
    reminder = sign_reminder(
        company="Hale & Ward LLP",
        signer="Maya Chen",
        document="Mutual NDA",
        url=URL,
        expires_at=EXPIRES,
    )
    assert reminder.subject == "Reminder: Mutual NDA is waiting for your signature"
    assert URL in reminder.body.text

    withdrawn = sign_withdrawn(company="Hale & Ward LLP", signer="Maya Chen", document="Mutual NDA")
    assert withdrawn.subject == "Hale & Ward LLP withdrew Mutual NDA"
    assert "the link you were sent no longer works" in withdrawn.body.text
    assert "https://" not in withdrawn.body.text  # nothing to open any more


def test_a_date_is_given_in_the_senders_zone_with_its_time() -> None:
    """Stored as 04:05 UTC on the 24th, it is the evening of the 23rd for a sender in California:
    the email says what the app shows them, not the next day."""
    expires = datetime(2026, 11, 24, 4, 5, tzinfo=UTC).astimezone(ZoneInfo("America/Los_Angeles"))
    letter = sign_reminder(
        company="Hale & Ward LLP",
        signer="Maya Chen",
        document="Mutual NDA",
        url=URL,
        expires_at=expires,
    )
    assert "It expires on Nov 23, 2026 at 8:05 PM PST." in letter.body.text


def test_a_zone_without_letters_is_given_by_its_distance_from_utc() -> None:
    """The tz database names Sao Paulo's time "-03" and India's "IST": a reader in another zone
    is told "UTC-3", never a bare "-03"."""

    def expiry(zone: str) -> str:
        expires = datetime(2026, 11, 24, 4, 5, tzinfo=UTC).astimezone(ZoneInfo(zone))
        text = sign_reminder(
            company="Hale & Ward LLP",
            signer="Maya Chen",
            document="Mutual NDA",
            url=URL,
            expires_at=expires,
        ).body.text
        return text.split("It expires on ", 1)[1].split(".", 1)[0]

    assert expiry("America/Sao_Paulo") == "Nov 24, 2026 at 1:05 AM UTC-3"
    assert expiry("Asia/Dubai") == "Nov 24, 2026 at 8:05 AM UTC+4"
    assert expiry("Asia/Kathmandu") == "Nov 24, 2026 at 9:50 AM UTC+5:45"
    assert expiry("Asia/Kolkata") == "Nov 24, 2026 at 9:35 AM IST"


def test_the_last_chance_reminder_says_when_the_link_stops_and_a_normal_one_does_not() -> None:
    def reminder(last_chance: bool) -> Letter:
        return sign_reminder(
            company="Hale & Ward LLP",
            signer="Maya Chen",
            document="Mutual NDA",
            url=URL,
            expires_at=EXPIRES,
            last_chance=last_chance,
        )

    last = reminder(True)
    normal = reminder(False)

    assert last.subject == "Reminder: Mutual NDA expires on Nov 23, 2026 at 12:00 PM UTC"
    assert "After Nov 23, 2026 at 12:00 PM UTC, this link stops working." in last.body.text
    assert normal.subject == "Reminder: Mutual NDA is waiting for your signature"
    assert "stops working" not in normal.body.text
