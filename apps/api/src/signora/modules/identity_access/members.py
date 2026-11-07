"""Members, roles, removal, workspace and profile (Phase 2 LLD topic 8).

The creator rule holds under concurrency because the role change and removal are single guarded
updates that exclude the workspace's creator in SQL.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, NotFound, ValidationFailed
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.identity_access import accounts
from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.errors import CannotRemoveSelf, CreatorProtected
from signora.modules.identity_access.sessions import delete_user_sessions


@dataclass(frozen=True)
class MemberRow:
    id: uuid.UUID
    name: str
    email: str
    role_id: uuid.UUID
    role_key: str
    role_name: str
    role_description: str
    is_creator: bool
    joined_at: datetime


_MEMBERS_SQL = """
    SELECT u.id, u.name, u.email, r.id AS role_id, r.key AS role_key, r.name AS role_name,
           r.description AS role_description, w.created_by = u.id AS is_creator,
           u.created_at AS joined_at
    FROM users u
    JOIN roles r ON r.id = u.role_id
    JOIN workspaces w ON w.id = u.workspace_id
    WHERE u.workspace_id = :w AND u.deactivated_at IS NULL
"""


def list_members(session: Session, workspace_id: uuid.UUID) -> list[MemberRow]:
    rows = session.execute(
        text(_MEMBERS_SQL + " ORDER BY is_creator DESC, lower(u.name)"), {"w": workspace_id}
    )
    return [MemberRow(**row._mapping) for row in rows]


def _member(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> MemberRow:
    row = session.execute(
        text(_MEMBERS_SQL + " AND u.id = :u"), {"w": workspace_id, "u": user_id}
    ).one_or_none()
    if row is None:
        raise NotFound
    return MemberRow(**row._mapping)


@dataclass(frozen=True)
class DirectoryEntry:
    id: uuid.UUID
    name: str
    email: str


def directory(session: Session, workspace_id: uuid.UUID) -> list[DirectoryEntry]:
    """Active colleagues for pickers: only what a picker needs, no roles or invites."""
    rows = session.execute(
        text(
            "SELECT id, name, email FROM users "
            "WHERE workspace_id = :w AND deactivated_at IS NULL ORDER BY lower(name)"
        ),
        {"w": workspace_id},
    )
    return [DirectoryEntry(**row._mapping) for row in rows]


@dataclass(frozen=True)
class RoleRow:
    id: uuid.UUID
    key: str
    name: str
    description: str
    is_system: bool
    permissions: list[str]


def list_roles(session: Session, workspace_id: uuid.UUID) -> list[RoleRow]:
    rows = session.execute(
        text(
            "SELECT id, key, name, description, is_system, permissions FROM roles "
            "WHERE workspace_id = :w ORDER BY is_system DESC, name"
        ),
        {"w": workspace_id},
    )
    return [RoleRow(**row._mapping) for row in rows]


def _audit(uow: UnitOfWork, actor: Actor, action: str, subject: Subject, **data: Any) -> None:
    record(
        uow,
        chain=AuditChain.workspace(actor.workspace_id),
        actor=accounts.audit_actor(actor.user_id, actor.email),
        action=action,
        subject=subject,
        data=data,
    )


def change_role(
    uow: UnitOfWork, *, actor: Actor, user_id: uuid.UUID, role_id: uuid.UUID
) -> MemberRow:
    """Takes effect on the member's next request (the role is read per request)."""
    member = _member(uow.session, actor.workspace_id, user_id)
    if member.is_creator:
        raise CreatorProtected
    new_role = uow.session.execute(
        text("SELECT name FROM roles WHERE id = :r AND workspace_id = :w"),
        {"r": role_id, "w": actor.workspace_id},
    ).scalar_one_or_none()
    if new_role is None:
        raise ValidationFailed([FieldError("role_id", "Choose one of this workspace's roles")])
    if member.role_id == role_id:
        return member
    changed = uow.session.execute(
        text(
            """
            UPDATE users SET role_id = :r
            WHERE id = :u AND workspace_id = :w AND deactivated_at IS NULL
              AND id <> (SELECT created_by FROM workspaces WHERE id = :w)
            """
        ),
        {"r": role_id, "u": user_id, "w": actor.workspace_id},
    ).rowcount  # type: ignore[attr-defined]
    if changed != 1:
        raise NotFound
    _audit(
        uow,
        actor,
        "member.role_changed",
        Subject("user", user_id),
        email=member.email,
        old_role=member.role_name,
        new_role=new_role,
    )
    return _member(uow.session, actor.workspace_id, user_id)


def remove_member(uow: UnitOfWork, *, actor: Actor, user_id: uuid.UUID) -> None:
    """Deactivates (keeps the user for history) and ends their sessions at once."""
    if user_id == actor.user_id:
        raise CannotRemoveSelf
    member = _member(uow.session, actor.workspace_id, user_id)
    if member.is_creator:
        raise CreatorProtected
    removed = uow.session.execute(
        text(
            """
            UPDATE users SET deactivated_at = now()
            WHERE id = :u AND workspace_id = :w AND deactivated_at IS NULL
              AND id <> (SELECT created_by FROM workspaces WHERE id = :w)
            """
        ),
        {"u": user_id, "w": actor.workspace_id},
    ).rowcount  # type: ignore[attr-defined]
    if removed != 1:
        raise NotFound
    ended = delete_user_sessions(uow.session, user_id)
    _audit(
        uow,
        actor,
        "member.removed",
        Subject("user", user_id),
        email=member.email,
        sessions_ended=ended,
    )


def rename_workspace(uow: UnitOfWork, *, actor: Actor, name: str) -> str:
    old = uow.session.execute(
        text("SELECT name FROM workspaces WHERE id = :w FOR UPDATE"), {"w": actor.workspace_id}
    ).scalar_one()
    if old != name:
        uow.session.execute(
            text("UPDATE workspaces SET name = :n WHERE id = :w"),
            {"n": name, "w": actor.workspace_id},
        )
        _audit(
            uow,
            actor,
            "workspace.renamed",
            Subject("workspace", actor.workspace_id),
            old_name=old,
            new_name=name,
        )
    return name


def rename_self(uow: UnitOfWork, *, actor: Actor, name: str) -> None:
    uow.session.execute(
        text("UPDATE users SET name = :n WHERE id = :u"), {"n": name, "u": actor.user_id}
    )
