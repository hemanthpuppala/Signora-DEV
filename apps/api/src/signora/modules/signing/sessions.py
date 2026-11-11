"""A browser's signing session and the people opened in it (Phase 8 LLD §1.3, §1.4).

The cookie holds a 256-bit token; the table holds its SHA-256. A session ends 30 minutes after its
last use (the ``.env`` setting) and 12 hours after it began. Each person opened in it is a grant:
a request acts only for the person its path names, and only with that person's grant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.modules.envelopes import SignerRecipient
from signora.modules.identity_access import IssuedToken, issue_token

COOKIE = "__Host-signora_sign"
LONGEST = timedelta(hours=12)
TOUCH = timedelta(minutes=1)  # the last use is written at most this often


def live_session(session: Session, digest: bytes, *, idle: timedelta) -> bool:
    """Whether the cookie's session is live; touches it when due."""
    row = session.execute(
        text(
            "SELECT last_seen_at < now() - make_interval(secs => :touch) AS due "
            "FROM signing_sessions WHERE id_hash = :h AND expires_at > now() "
            "AND last_seen_at > now() - make_interval(secs => :idle)"
        ),
        {"h": digest, "idle": idle.total_seconds(), "touch": TOUCH.total_seconds()},
    ).one_or_none()
    if row is None:
        return False
    if row.due:
        session.execute(
            text("UPDATE signing_sessions SET last_seen_at = now() WHERE id_hash = :h"),
            {"h": digest},
        )
    return True


def create_session(session: Session) -> IssuedToken:
    token = issue_token()
    session.execute(
        text(
            "INSERT INTO signing_sessions (id_hash, expires_at) "
            "VALUES (:h, now() + make_interval(secs => :longest))"
        ),
        {"h": token.digest, "longest": LONGEST.total_seconds()},
    )
    return token


def grant(session: Session, digest: bytes, recipient: SignerRecipient) -> None:
    """The person opened in this browser session. A link of a newer version (a corrected email)
    replaces the grant and its verification: the new link proves the new inbox."""
    session.execute(
        text(
            """
            INSERT INTO signing_grants (session_hash, recipient_id, workspace_id, link_version)
            VALUES (:h, :r, :w, :v)
            ON CONFLICT (session_hash, recipient_id) DO UPDATE
            SET link_version = EXCLUDED.link_version,
                verified_at = CASE WHEN signing_grants.link_version = EXCLUDED.link_version
                                   THEN signing_grants.verified_at END
            """
        ),
        {
            "h": digest,
            "r": recipient.id,
            "w": recipient.workspace_id,
            "v": recipient.link_version,
        },
    )


@dataclass(frozen=True)
class Grant:
    link_version: int
    verified_at: datetime | None


def read_grant(session: Session, digest: bytes, recipient_id: uuid.UUID) -> Grant | None:
    row = session.execute(
        text(
            "SELECT link_version, verified_at FROM signing_grants "
            "WHERE session_hash = :h AND recipient_id = :r"
        ),
        {"h": digest, "r": recipient_id},
    ).one_or_none()
    return Grant(row.link_version, row.verified_at) if row is not None else None
