"""Server-side sessions (Phase 2 LLD §4.1-4.2).

The cookie holds a 256-bit token; the table holds its SHA-256. A session ends after the idle
limit; its last activity is written at most once per touch interval.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.modules.identity_access.access import Actor, effective_permissions
from signora.modules.identity_access.domain.tokens import IssuedToken, issue_token


def create_session(
    session: Session, user_id: uuid.UUID, *, ip: str | None, user_agent: str | None
) -> IssuedToken:
    token = issue_token()
    session.execute(
        text(
            "INSERT INTO sessions (id_hash, user_id, ip, user_agent) "
            "VALUES (:h, :u, CAST(:ip AS inet), :ua)"
        ),
        {"h": token.digest, "u": user_id, "ip": ip, "ua": user_agent},
    )
    return token


def resolve_session(
    session: Session, digest: bytes, *, idle: timedelta, touch: timedelta
) -> Actor | None:
    """The actor of a live session of an active user, or ``None``. Touches it when due."""
    row = session.execute(
        text(
            """
            SELECT s.user_id, s.last_seen_at < now() - make_interval(secs => :touch) AS due,
                   u.email, u.name, u.workspace_id, w.name AS workspace_name,
                   w.created_by = u.id AS is_creator,
                   r.id AS role_id, r.key AS role_key, r.name AS role_name,
                   r.description AS role_description, r.permissions
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            JOIN workspaces w ON w.id = u.workspace_id
            JOIN roles r ON r.id = u.role_id
            WHERE s.id_hash = :digest
              AND s.last_seen_at > now() - make_interval(secs => :idle)
              AND u.deactivated_at IS NULL
            """
        ),
        {"digest": digest, "idle": idle.total_seconds(), "touch": touch.total_seconds()},
    ).one_or_none()
    if row is None:
        return None
    if row.due:
        session.execute(
            text("UPDATE sessions SET last_seen_at = now() WHERE id_hash = :digest"),
            {"digest": digest},
        )
    return _actor(row, digest)


def _actor(row: Any, digest: bytes) -> Actor:
    """The actor a row of a user, their company and their role describes."""
    return Actor(
        user_id=row.user_id,
        email=row.email,
        name=row.name,
        workspace_id=row.workspace_id,
        workspace_name=row.workspace_name,
        role_id=row.role_id,
        role_key=row.role_key,
        role_name=row.role_name,
        role_description=row.role_description,
        permissions=effective_permissions(row.permissions, is_creator=row.is_creator),
        is_creator=row.is_creator,
        session_digest=digest,
    )


def actor_of(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Actor | None:
    """An active user as an actor, with the role they hold now and no session: for background
    work done in their name (a bulk send's job), so it passes through the same access checks a
    request of theirs would. ``None`` once they are deactivated."""
    row = session.execute(
        text(
            """
            SELECT u.id AS user_id, u.email, u.name, u.workspace_id, w.name AS workspace_name,
                   w.created_by = u.id AS is_creator,
                   r.id AS role_id, r.key AS role_key, r.name AS role_name,
                   r.description AS role_description, r.permissions
            FROM users u
            JOIN workspaces w ON w.id = u.workspace_id
            JOIN roles r ON r.id = u.role_id
            WHERE u.id = :user AND u.workspace_id = :workspace AND u.deactivated_at IS NULL
            """
        ),
        {"user": user_id, "workspace": workspace_id},
    ).one_or_none()
    return None if row is None else _actor(row, b"")


def delete_session(session: Session, digest: bytes) -> None:
    session.execute(text("DELETE FROM sessions WHERE id_hash = :d"), {"d": digest})


def delete_user_sessions(session: Session, user_id: uuid.UUID, *, keep: bytes | None = None) -> int:
    """End every session of a user (optionally except the current one); returns how many."""
    result = session.execute(
        text(
            "DELETE FROM sessions WHERE user_id = :u "
            "AND (CAST(:keep AS bytea) IS NULL OR id_hash <> :keep)"
        ),
        {"u": user_id, "keep": keep},
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


def purge_idle_sessions(session: Session, idle: timedelta) -> None:
    session.execute(
        text("DELETE FROM sessions WHERE last_seen_at < now() - make_interval(secs => :idle)"),
        {"idle": idle.total_seconds()},
    )
