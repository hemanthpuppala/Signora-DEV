"""Workspaces and users (Phase 2 LLD topics 1, 5, 8).

Every function that reads or changes workspace data takes the workspace id explicitly; callers pass
the one from the session, never one from the request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.db import UnitOfWork
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.identity_access.domain.permissions import CREATOR_ROLE, DEFAULT_ROLES


@dataclass(frozen=True)
class UserRow:
    id: uuid.UUID
    workspace_id: uuid.UUID
    workspace_name: str
    email: str
    name: str
    password_hash: str
    deactivated_at: datetime | None

    @property
    def active(self) -> bool:
        return self.deactivated_at is None


def find_user_by_email(session: Session, email: str) -> UserRow | None:
    """``email`` must already be normalised."""
    row = session.execute(
        text(
            """
            SELECT u.id, u.workspace_id, w.name AS workspace_name, u.email, u.name,
                   u.password_hash, u.deactivated_at
            FROM users u JOIN workspaces w ON w.id = u.workspace_id
            WHERE u.email = :email
            """
        ),
        {"email": email},
    ).one_or_none()
    return UserRow(**row._mapping) if row else None


def lock_email(session: Session, email: str) -> None:
    """Serialise account creation for one address until the transaction ends (sign-up and invite
    acceptance), so two concurrent attempts cannot both pass the "no account yet" check."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"account-email:{email}"},
    )


def audit_actor(user_id: uuid.UUID, email: str) -> AuditActor:
    return AuditActor("user", user_id, email)


@dataclass(frozen=True)
class CreatedWorkspace:
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    role_ids: dict[str, uuid.UUID]


def create_workspace(
    uow: UnitOfWork, *, workspace_name: str, creator_name: str, email: str, password_hash: str
) -> CreatedWorkspace:
    """The workspace, its default roles and its creator, in the caller's transaction.

    The creator's foreign key is deferred, so all rows are checked together at commit.
    """
    session = uow.session
    workspace_id, user_id = session.execute(text("SELECT uuidv7(), uuidv7()")).one()
    session.execute(
        text("INSERT INTO workspaces (id, name, created_by) VALUES (:w, :name, :u)"),
        {"w": workspace_id, "name": workspace_name, "u": user_id},
    )
    role_ids: dict[str, uuid.UUID] = {}
    for template in DEFAULT_ROLES:
        role_ids[template.key] = session.execute(
            text(
                "INSERT INTO roles (workspace_id, key, name, permissions, is_system) "
                "VALUES (:w, :key, :name, :permissions, true) RETURNING id"
            ),
            {
                "w": workspace_id,
                "key": template.key,
                "name": template.name,
                "permissions": sorted(template.permissions),
            },
        ).scalar_one()
    session.execute(
        text(
            "INSERT INTO users (id, workspace_id, role_id, email, name, password_hash) "
            "VALUES (:u, :w, :r, :email, :name, :hash)"
        ),
        {
            "u": user_id,
            "w": workspace_id,
            "r": role_ids[CREATOR_ROLE.key],
            "email": email,
            "name": creator_name,
            "hash": password_hash,
        },
    )
    chain = AuditChain.workspace(workspace_id)
    actor = audit_actor(user_id, email)
    record(
        uow,
        chain=chain,
        actor=actor,
        action="workspace.created",
        subject=Subject("workspace", workspace_id),
        data={"name": workspace_name},
    )
    record(
        uow,
        chain=chain,
        actor=actor,
        action="member.joined",
        subject=Subject("user", user_id),
        data={"role": CREATOR_ROLE.key, "creator": True},
    )
    return CreatedWorkspace(workspace_id, user_id, role_ids)


def set_password(session: Session, user_id: uuid.UUID, password_hash: str) -> None:
    session.execute(
        text("UPDATE users SET password_hash = :hash, password_changed_at = now() WHERE id = :id"),
        {"id": user_id, "hash": password_hash},
    )


def upgrade_password_hash(session: Session, user_id: uuid.UUID, password_hash: str) -> None:
    """Same password, stronger parameters: ``password_changed_at`` is not touched."""
    session.execute(
        text("UPDATE users SET password_hash = :hash WHERE id = :id"),
        {"id": user_id, "hash": password_hash},
    )


def record_login(session: Session, user_id: uuid.UUID) -> None:
    session.execute(text("UPDATE users SET last_login_at = now() WHERE id = :id"), {"id": user_id})
