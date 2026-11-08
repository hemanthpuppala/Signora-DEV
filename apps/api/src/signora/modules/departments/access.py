"""Access inside a department (Phase 3 LLD topic 2).

The company role is the baseline in every department; a grant adds the department permissions in
one department. ``can`` is a set lookup over the actor's grants, loaded once per request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, PermissionDenied, ValidationFailed
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.departments.service import get_department, lock_active_department
from signora.modules.identity_access import DEPARTMENT_GRANT, Actor, Permission

Access = Literal["edit", "read"]


@dataclass(frozen=True)
class DepartmentAccess:
    """The actor's grants (department ids), loaded with one indexed query."""

    actor: Actor
    granted: frozenset[uuid.UUID]

    def can(self, permission: Permission, department_id: uuid.UUID) -> bool:
        if self.actor.can(permission):
            return True
        return permission in DEPARTMENT_GRANT and department_id in self.granted

    def level(self, department_id: uuid.UUID) -> Access:
        return "edit" if self.can(Permission.FILES_SEND, department_id) else "read"

    def require(self, permission: Permission, department_id: uuid.UUID) -> None:
        if not self.can(permission, department_id):
            raise PermissionDenied


def load_access(session: Session, actor: Actor) -> DepartmentAccess:
    granted = session.execute(
        text(
            "SELECT department_id FROM department_grants WHERE user_id = :u AND workspace_id = :w"
        ),
        {"u": actor.user_id, "w": actor.workspace_id},
    ).scalars()
    return DepartmentAccess(actor, frozenset(granted))


@dataclass(frozen=True)
class GrantRow:
    user_id: uuid.UUID
    user_name: str
    user_email: str
    granted_by_id: uuid.UUID
    granted_by_name: str
    created_at: Any


def list_grants(
    session: Session, workspace_id: uuid.UUID, department_id: uuid.UUID
) -> list[GrantRow]:
    get_department(session, workspace_id, department_id)  # 404 for another company's id
    rows = session.execute(
        text(
            """
            SELECT g.user_id, u.name AS user_name, u.email AS user_email,
                   g.granted_by AS granted_by_id, b.name AS granted_by_name, g.created_at
            FROM department_grants g
            JOIN users u ON u.id = g.user_id
            JOIN users b ON b.id = g.granted_by
            WHERE g.department_id = :d AND g.workspace_id = :w
            ORDER BY lower(u.name), u.id
            """
        ),
        {"d": department_id, "w": workspace_id},
    )
    return [GrantRow(**row._mapping) for row in rows]


# Active members whose role already gives edit access in every department (the creator holds every
# permission in code; a role holding files.send edits everywhere). A grant adds nothing for them.
_EDITS_EVERYWHERE = "(u.id = w.created_by OR CAST(:send AS text) = ANY(r.permissions))"
_MEMBERS = (
    "FROM users u JOIN roles r ON r.id = u.role_id JOIN workspaces w ON w.id = u.workspace_id "
    "WHERE u.workspace_id = :w AND u.deactivated_at IS NULL"
)


@dataclass(frozen=True)
class Candidate:
    id: uuid.UUID
    name: str
    email: str


def grant_candidates(
    session: Session, workspace_id: uuid.UUID, department_id: uuid.UUID
) -> list[Candidate]:
    """Active members a grant would help: not the creator, not roles that edit everywhere."""
    get_department(session, workspace_id, department_id)
    rows = session.execute(
        text(
            f"SELECT u.id, u.name, u.email {_MEMBERS} AND NOT {_EDITS_EVERYWHERE} "
            "ORDER BY lower(u.name), u.id"
        ),
        {"w": workspace_id, "send": Permission.FILES_SEND.value},
    )
    return [Candidate(**row._mapping) for row in rows]


def set_grants(
    uow: UnitOfWork, *, actor: Actor, department_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> list[GrantRow]:
    """Replace the list in one transaction; audit each person added or removed."""
    lock_active_department(uow.session, actor.workspace_id, department_id)
    wanted = list(dict.fromkeys(user_ids))  # order kept, duplicates merged
    active = set(
        uow.session.execute(
            text(
                "SELECT id FROM users WHERE workspace_id = :w AND deactivated_at IS NULL "
                "AND id = ANY(:ids)"
            ),
            {"w": actor.workspace_id, "ids": wanted},
        ).scalars()
    )
    edits_everywhere = set(
        uow.session.execute(
            text(f"SELECT u.id {_MEMBERS} AND u.id = ANY(:ids) AND {_EDITS_EVERYWHERE}"),
            {"w": actor.workspace_id, "ids": wanted, "send": Permission.FILES_SEND.value},
        ).scalars()
    )
    errors = [
        FieldError(f"user_ids[{i}]", "Choose an active member of this company")
        for i, user_id in enumerate(wanted)
        if user_id not in active
    ] + [
        FieldError(f"user_ids[{i}]", "Already has edit access through their role")
        for i, user_id in enumerate(wanted)
        if user_id in edits_everywhere
    ]
    if errors:
        raise ValidationFailed(errors)
    current = set(
        uow.session.execute(
            text("SELECT user_id FROM department_grants WHERE department_id = :d"),
            {"d": department_id},
        ).scalars()
    )
    added = [u for u in wanted if u not in current]
    removed = [u for u in current if u not in set(wanted)]
    if removed:
        uow.session.execute(
            text("DELETE FROM department_grants WHERE department_id = :d AND user_id = ANY(:ids)"),
            {"d": department_id, "ids": removed},
        )
    for user_id in added:
        uow.session.execute(
            text(
                "INSERT INTO department_grants (department_id, workspace_id, user_id, granted_by) "
                "VALUES (:d, :w, :u, :by)"
            ),
            {"d": department_id, "w": actor.workspace_id, "u": user_id, "by": actor.user_id},
        )
    for action, people in (
        ("department.access_granted", added),
        ("department.access_revoked", removed),
    ):
        for user_id in people:
            record(
                uow,
                chain=AuditChain.workspace(actor.workspace_id),
                actor=AuditActor("user", actor.user_id, actor.email),
                action=action,
                subject=Subject("department", department_id),
                data={"user_id": str(user_id)},
            )
    return list_grants(uow.session, actor.workspace_id, department_id)


def revoke_removed_member(uow: UnitOfWork, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Member-removal hook: the person's edit access ends in every department."""
    uow.session.execute(
        text("DELETE FROM department_grants WHERE workspace_id = :w AND user_id = :u"),
        {"w": workspace_id, "u": user_id},
    )
