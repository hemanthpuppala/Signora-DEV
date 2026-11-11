"""Consent to electronic records (Phase 8 LLD §3): the disclosure, versioned, and its record.

The disclosure is the consumer disclosure of the US ESIGN Act (15 U.S.C. §7001(c)): what it
covers, the right to a paper copy, how to withdraw consent, and what is needed to sign and keep
the records. One text, here; a changed text is a new version, and what a person agreed to is never
rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from signora.kernel.context import current_origin
from signora.kernel.db import UnitOfWork
from signora.modules.envelopes import SignerRecipient

VERSION = "esign-disclosure-v1"
AGREEMENT = "I agree to use electronic records and signatures."
_USER_AGENT = 512


@dataclass(frozen=True)
class Paragraph:
    title: str
    text: str


def disclosure(company: str, sender_email: str) -> list[Paragraph]:
    return [
        Paragraph(
            "What this covers",
            f"{company} wants to give you this agreement and collect your signature "
            "electronically. You sign it and keep it electronically.",
        ),
        Paragraph(
            "A paper copy",
            f"You may ask for a paper copy at any time by writing to {sender_email}. "
            "There is no fee.",
        ),
        Paragraph(
            "Withdrawing consent",
            "You can withdraw your consent before you sign by choosing Decline. It does not "
            "affect anything you signed earlier. To change the email you are reached at, write "
            f"to {sender_email}.",
        ),
        Paragraph(
            "What you need",
            "A current web browser, access to this email address, and a way to open PDF files. "
            "You can download a copy of everything you sign.",
        ),
    ]


def has_consented(uow: UnitOfWork, recipient_id: object) -> bool:
    return bool(
        uow.session.execute(
            text("SELECT EXISTS (SELECT 1 FROM signing_consents WHERE recipient_id = :r)"),
            {"r": recipient_id},
        ).scalar_one()
    )


def record_consent(uow: UnitOfWork, recipient: SignerRecipient) -> bool:
    """Keep the consent with the request's IP and user agent. ``True`` only the first time: a
    repeat changes nothing."""
    origin = current_origin()
    agent = origin.user_agent if origin else None
    row = uow.session.execute(
        text(
            """
            INSERT INTO signing_consents (recipient_id, workspace_id, disclosure_version, ip,
                                          user_agent)
            VALUES (:r, :w, :v, CAST(:ip AS inet), :ua)
            ON CONFLICT (recipient_id) DO NOTHING
            RETURNING recipient_id
            """
        ),
        {
            "r": recipient.id,
            "w": recipient.workspace_id,
            "v": VERSION,
            "ip": origin.ip if origin else None,
            "ua": agent[:_USER_AGENT] if agent else None,
        },
    ).one_or_none()
    return row is not None
