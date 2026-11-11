"""The words of the emails a send causes (Phase 7 LLD §5), in the shared layout.

Short and calm: who asks, what, one button, the link printed under it (the layout does that), when
it expires, and that a reply reaches the sender.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from signora.modules.notifications import EmailAction, RenderedEmail, render_layout


@dataclass(frozen=True)
class Letter:
    subject: str
    body: RenderedEmail


def moment_in_words(moment: datetime) -> str:
    """A moment as its reader takes it, in the zone it carries (the sender's): "Nov 23, 2026 at
    8:05 PM PST". With the time and the zone, a date near midnight cannot be read as the next."""
    hour = moment.strftime("%I").lstrip("0")
    return f"{moment:%b} {moment.day}, {moment.year} at {hour}:{moment:%M %p} {_zone(moment)}"


def _zone(moment: datetime) -> str:
    """The zone's letters ("PST"), or where it has none (Sao Paulo, Dubai: the tz database gives
    "-03", "+04") its distance from UTC: "UTC-3", "UTC+5:30"."""
    name = moment.tzname() or "UTC"
    if name.isalpha():
        return name
    minutes = round((moment.utcoffset() or timedelta()).total_seconds() / 60)
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{'-' if minutes < 0 else '+'}{hours}" + (f":{rest:02d}" if rest else "")


def _first(name: str) -> str:
    return name.strip().split(" ")[0] or name


def sign_request(
    *, company: str, sender: str, signer: str, document: str, url: str, expires_at: datetime
) -> Letter:
    heading = f"{company} asks you to sign {document}"
    return Letter(
        subject=heading,
        body=render_layout(
            heading=heading,
            paragraphs=[
                f"Hi {_first(signer)}, {sender} sent you this to review and sign. "
                "It takes a few minutes."
            ],
            action=EmailAction("Review and sign", url),
            footer=f"This link is for you only. It expires on {moment_in_words(expires_at)}. "
            "Questions? Reply to this email.",
        ),
    )


def sign_reminder(
    *, company: str, signer: str, document: str, url: str, expires_at: datetime
) -> Letter:
    heading = f"{document} is waiting for your signature"
    return Letter(
        subject=f"Reminder: {heading}",
        body=render_layout(
            heading=heading,
            paragraphs=[f"Hi {_first(signer)}, {company} is still waiting for you to sign."],
            action=EmailAction("Review and sign", url),
            footer=f"This link is for you only. It expires on {moment_in_words(expires_at)}. "
            "Questions? Reply to this email.",
        ),
    )


def sign_withdrawn(*, company: str, signer: str, document: str) -> Letter:
    heading = f"{company} withdrew {document}"
    return Letter(
        subject=heading,
        body=render_layout(
            heading=heading,
            paragraphs=[
                f"Hi {_first(signer)}, there is nothing for you to sign any more: "
                "the link you were sent no longer works.",
            ],
            footer="Questions? Reply to this email.",
        ),
    )
