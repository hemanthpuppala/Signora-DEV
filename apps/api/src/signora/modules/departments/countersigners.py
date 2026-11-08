"""Who may countersign for a department, in default order (Phase 3 LLD topic 4).

How many firm signatures a file needs comes from the file (Phases 5-6); this list supplies the
people, in order, as send-time defaults (Phase 7). Any active member may be listed; the list has no
size limit. A removed member leaves every list in the removal's own transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, ValidationFailed
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.departments.service import get_department, require_active
from signora.modules.identity_access import Actor


@dataclass(frozen=True)
class Countersigner:
    id: uuid.UUID
    name: str
    email: str


def list_countersigners(
    session: Session, workspace_id: uuid.UUID, department_id: uuid.UUID
) -> list[Countersigner]:
    rows = session.execute(
        text(
            """
            SELECT u.id, u.name, u.email
            FROM department_countersigners c JOIN users u ON u.id = c.user_id
            WHERE c.department_id = :d AND c.workspace_id = :w AND u.deactivated_at IS NULL
            ORDER BY c.position
            """
        ),
        {"d": department_id, "w": workspace_id},
    )
    return [Countersigner(**row._mapping) for row in rows]


def set_countersigners(
    uow: UnitOfWork, *, actor: Actor, department_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> list[Countersigner]:
    """Replace the ordered list in one transaction (repeat-safe)."""
    require_active(get_department(uow.session, actor.workspace_id, department_id))
    errors: list[FieldError] = []
    seen: set[uuid.UUID] = set()
    for index, user_id in enumerate(user_ids):
        if user_id in seen:
            errors.append(FieldError(f"user_ids[{index}]", "Listed twice"))
        seen.add(user_id)
    active = set(
        uow.session.execute(
            text(
                "SELECT id FROM users WHERE workspace_id = :w AND deactivated_at IS NULL "
                "AND id = ANY(:ids)"
            ),
            {"w": actor.workspace_id, "ids": list(seen)},
        ).scalars()
    )
    errors += [
        FieldError(f"user_ids[{i}]", "Choose an active member of this company")
        for i, user_id in enumerate(user_ids)
        if user_id not in active
    ]
    if errors:
        raise ValidationFailed(errors)

    before = [
        row.user_id
        for row in uow.session.execute(
            text(
                "SELECT user_id FROM department_countersigners WHERE department_id = :d "
                "ORDER BY position FOR UPDATE"
            ),
            {"d": department_id},
        )
    ]
    if before == user_ids:
        return list_countersigners(uow.session, actor.workspace_id, department_id)
    uow.session.execute(
        text("DELETE FROM department_countersigners WHERE department_id = :d"),
        {"d": department_id},
    )
    for position, user_id in enumerate(user_ids, start=1):
        uow.session.execute(
            text(
                "INSERT INTO department_countersigners "
                "(department_id, workspace_id, user_id, position, added_by) "
                "VALUES (:d, :w, :u, :p, :by)"
            ),
            {
                "d": department_id,
                "w": actor.workspace_id,
                "u": user_id,
                "p": position,
                "by": actor.user_id,
            },
        )

    def audit(action: str, **data: object) -> None:
        record(
            uow,
            chain=AuditChain.workspace(actor.workspace_id),
            actor=AuditActor("user", actor.user_id, actor.email),
            action=action,
            subject=Subject("department", department_id),
            data=data,
        )

    added = [u for u in user_ids if u not in before]
    removed = [u for u in before if u not in user_ids]
    for user_id in added:
        audit("department.countersigner_added", user_id=str(user_id))
    for user_id in removed:
        audit("department.countersigner_removed", user_id=str(user_id))
    kept_before = [u for u in before if u in user_ids]
    kept_after = [u for u in user_ids if u in before]
    if kept_before != kept_after:
        audit("department.countersigners_reordered", order=[str(u) for u in user_ids])
    return list_countersigners(uow.session, actor.workspace_id, department_id)


def drop_removed_member(uow: UnitOfWork, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Member-removal hook: the person leaves every department's countersigner list."""
    uow.session.execute(
        text("DELETE FROM department_countersigners WHERE workspace_id = :w AND user_id = :u"),
        {"w": workspace_id, "u": user_id},
    )
