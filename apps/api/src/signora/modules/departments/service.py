"""Departments: create, list, read, update, archive, restore (Phase 3 LLD topic 1).

Every function takes the company from the caller's ``Actor`` (the session), never from the request.
Name uniqueness is enforced by the partial unique index; a losing concurrent request is answered
``409 department-name-taken``, never a 500.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, NotFound, ValidationFailed
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.departments.domain import description_problem, name_problem, normalize_name
from signora.modules.departments.errors import DepartmentArchived, DepartmentNameTaken
from signora.modules.identity_access import Actor

ACTIVE_NAME_INDEX = "uq_departments_active_name"
LIST_LIMIT = 500

Status = Literal["active", "archived"]


@dataclass(frozen=True)
class DepartmentRow:
    id: uuid.UUID
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    created_by_id: uuid.UUID
    created_by_name: str

    @property
    def status(self) -> Status:
        return "archived" if self.archived_at is not None else "active"


_SELECT = """
    SELECT d.id, d.name, d.description, d.created_at, d.updated_at, d.archived_at,
           d.created_by AS created_by_id, u.name AS created_by_name
    FROM departments d JOIN users u ON u.id = d.created_by
    WHERE d.workspace_id = :w
"""


def _row(session: Session, workspace_id: uuid.UUID, department_id: uuid.UUID) -> DepartmentRow:
    found = session.execute(
        text(_SELECT + " AND d.id = :id"), {"w": workspace_id, "id": department_id}
    ).one_or_none()
    if found is None:
        raise NotFound
    return DepartmentRow(**found._mapping)


def get_department(
    session: Session, workspace_id: uuid.UUID, department_id: uuid.UUID
) -> DepartmentRow:
    """The company's department, or ``404`` (also for another company's id)."""
    return _row(session, workspace_id, department_id)


def require_active(department: DepartmentRow) -> None:
    if department.archived_at is not None:
        raise DepartmentArchived


def list_departments(
    session: Session, workspace_id: uuid.UUID, status: Status
) -> list[DepartmentRow]:
    rows = session.execute(
        text(
            _SELECT + " AND (d.archived_at IS NULL) = :active "
            "ORDER BY lower(d.name), d.id LIMIT :limit"
        ),
        {"w": workspace_id, "active": status == "active", "limit": LIST_LIMIT},
    )
    return [DepartmentRow(**row._mapping) for row in rows]


def _valid_name(raw: str) -> str:
    name = normalize_name(raw)
    if (problem := name_problem(name)) is not None:
        raise ValidationFailed([FieldError("name", problem)])
    return name


def _valid_description(raw: str) -> str:
    description = raw.strip()
    if (problem := description_problem(description)) is not None:
        raise ValidationFailed([FieldError("description", problem)])
    return description


def _name_taken(error: IntegrityError) -> bool:
    return ACTIVE_NAME_INDEX in str(error.orig)


def _audit(
    uow: UnitOfWork, actor: Actor, action: str, department_id: uuid.UUID, **data: Any
) -> None:
    record(
        uow,
        chain=AuditChain.workspace(actor.workspace_id),
        actor=AuditActor("user", actor.user_id, actor.email),
        action=action,
        subject=Subject("department", department_id),
        data=data,
    )


def create_department(
    uow: UnitOfWork, *, actor: Actor, name: str, description: str = ""
) -> DepartmentRow:
    clean_name, clean_description = _valid_name(name), _valid_description(description)
    try:
        with uow.session.begin_nested():  # a lost name race rolls back only this insert
            department_id = uow.session.execute(
                text(
                    "INSERT INTO departments (workspace_id, name, description, created_by) "
                    "VALUES (:w, :n, :d, :u) RETURNING id"
                ),
                {
                    "w": actor.workspace_id,
                    "n": clean_name,
                    "d": clean_description,
                    "u": actor.user_id,
                },
            ).scalar_one()
    except IntegrityError as error:
        if _name_taken(error):
            raise DepartmentNameTaken from None
        raise
    _audit(uow, actor, "department.created", department_id, name=clean_name)
    return _row(uow.session, actor.workspace_id, department_id)


def update_department(
    uow: UnitOfWork,
    *,
    actor: Actor,
    department_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
) -> DepartmentRow:
    current = _row(uow.session, actor.workspace_id, department_id)
    require_active(current)
    changes: dict[str, tuple[str, str]] = {}
    if name is not None and (new_name := _valid_name(name)) != current.name:
        changes["name"] = (current.name, new_name)
    if description is not None and (new_desc := _valid_description(description)) != (
        current.description
    ):
        changes["description"] = (current.description, new_desc)
    if not changes:
        return current
    values = {field: new for field, (_, new) in changes.items()}
    assignments = ", ".join(f"{field} = :{field}" for field in values)
    try:
        with uow.session.begin_nested():
            uow.session.execute(
                text(
                    f"UPDATE departments SET {assignments}, updated_at = now() "  # noqa: S608 - field names from this module
                    "WHERE id = :id AND workspace_id = :w AND archived_at IS NULL"
                ),
                {"id": department_id, "w": actor.workspace_id, **values},
            )
    except IntegrityError as error:
        if _name_taken(error):
            raise DepartmentNameTaken from None
        raise
    _audit(
        uow,
        actor,
        "department.updated",
        department_id,
        changes={field: {"old": old, "new": new} for field, (old, new) in changes.items()},
    )
    return _row(uow.session, actor.workspace_id, department_id)


def archive_department(uow: UnitOfWork, *, actor: Actor, department_id: uuid.UUID) -> DepartmentRow:
    """Repeat-safe: archiving an archived department returns it unchanged."""
    changed = uow.session.execute(
        text(
            "UPDATE departments SET archived_at = now(), archived_by = :u, updated_at = now() "
            "WHERE id = :id AND workspace_id = :w AND archived_at IS NULL RETURNING id"
        ),
        {"id": department_id, "w": actor.workspace_id, "u": actor.user_id},
    ).one_or_none()
    if changed is not None:
        _audit(uow, actor, "department.archived", department_id)
    return _row(uow.session, actor.workspace_id, department_id)


def restore_department(uow: UnitOfWork, *, actor: Actor, department_id: uuid.UUID) -> DepartmentRow:
    """Repeat-safe; ``409 department-name-taken`` when an active department now has the name."""
    try:
        with uow.session.begin_nested():
            changed = uow.session.execute(
                text(
                    "UPDATE departments SET archived_at = NULL, archived_by = NULL, "
                    "updated_at = now() "
                    "WHERE id = :id AND workspace_id = :w AND archived_at IS NOT NULL RETURNING id"
                ),
                {"id": department_id, "w": actor.workspace_id},
            ).one_or_none()
    except IntegrityError as error:
        if _name_taken(error):
            raise DepartmentNameTaken(
                "An active department now has this name. Rename that one first"
            ) from None
        raise
    if changed is not None:
        _audit(uow, actor, "department.restored", department_id)
    return _row(uow.session, actor.workspace_id, department_id)
