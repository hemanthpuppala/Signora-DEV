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
from signora.modules.departments.domain import (
    EXPIRY_DAYS,
    MAX_REMINDERS,
    NOTIFY_EMAILS_MAX,
    REMINDER_INTERVAL_HOURS,
    description_problem,
    name_problem,
    normalize_name,
    range_problem,
)
from signora.modules.departments.errors import DepartmentArchived, DepartmentNameTaken
from signora.modules.identity_access import Actor, InvalidEmailError, normalize_email

ACTIVE_NAME_INDEX = "uq_departments_active_name"
LIST_LIMIT = 500

Status = Literal["active", "archived"]


@dataclass(frozen=True)
class Settings:
    reminder_interval_hours: int
    max_reminders: int
    expiry_days: int
    notify_emails: tuple[str, ...]


@dataclass(frozen=True)
class SettingsChange:
    """Fields to change; ``None`` leaves a setting as it is."""

    reminder_interval_hours: int | None = None
    max_reminders: int | None = None
    expiry_days: int | None = None
    notify_emails: list[str] | None = None


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
    reminder_interval_hours: int
    max_reminders: int
    expiry_days: int
    notify_emails: list[str]

    @property
    def settings(self) -> Settings:
        return Settings(
            self.reminder_interval_hours,
            self.max_reminders,
            self.expiry_days,
            tuple(self.notify_emails),
        )

    @property
    def status(self) -> Status:
        return "archived" if self.archived_at is not None else "active"


_SELECT = """
    SELECT d.id, d.name, d.description, d.created_at, d.updated_at, d.archived_at,
           d.created_by AS created_by_id, u.name AS created_by_name,
           d.reminder_interval_hours, d.max_reminders, d.expiry_days, d.notify_emails
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


def lock_active_department(
    session: Session, workspace_id: uuid.UUID, department_id: uuid.UUID
) -> None:
    """Hold the department's row lock until commit, so replacing one of its lists is serialised.

    Locking the list rows is not enough: an empty list has no rows to lock, so two first additions
    would both insert. ``NO KEY UPDATE`` still lets other tables reference the department.
    """
    found = session.execute(
        text(
            "SELECT archived_at FROM departments WHERE id = :id AND workspace_id = :w "
            "FOR NO KEY UPDATE"
        ),
        {"id": department_id, "w": workspace_id},
    ).one_or_none()
    if found is None:
        raise NotFound
    if found.archived_at is not None:
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


def _valid_emails(raw: list[str]) -> list[str]:
    """Normalised with the identity module's one definition of an email; duplicates merged."""
    clean: list[str] = []
    errors: list[FieldError] = []
    for index, value in enumerate(raw):
        try:
            email = normalize_email(value)
        except InvalidEmailError as error:
            errors.append(FieldError(f"notify_emails[{index}]", str(error)))
            continue
        if email not in clean:
            clean.append(email)
    if len(clean) > NOTIFY_EMAILS_MAX:
        errors.append(FieldError("notify_emails", f"Add {NOTIFY_EMAILS_MAX} or fewer emails"))
    if errors:
        raise ValidationFailed(errors)
    return clean


def _valid_settings(change: SettingsChange) -> dict[str, Any]:
    """The given settings, checked; the database checks the same ranges."""
    values: dict[str, Any] = {}
    errors: list[FieldError] = []
    for field, bounds in (
        ("reminder_interval_hours", REMINDER_INTERVAL_HOURS),
        ("max_reminders", MAX_REMINDERS),
        ("expiry_days", EXPIRY_DAYS),
    ):
        value = getattr(change, field)
        if value is None:
            continue
        if (problem := range_problem(value, bounds)) is not None:
            errors.append(FieldError(field, problem))
        values[field] = value
    if change.notify_emails is not None:
        try:
            values["notify_emails"] = _valid_emails(change.notify_emails)
        except ValidationFailed as error:
            errors.extend(error.field_errors)
    if errors:
        raise ValidationFailed(errors)
    return values


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
    uow: UnitOfWork,
    *,
    actor: Actor,
    name: str,
    description: str = "",
    defaults: Settings,
    overrides: SettingsChange | None = None,
) -> DepartmentRow:
    """Settings start from the company ``defaults`` (copied, not inherited: topic 3)."""
    clean_name, clean_description = _valid_name(name), _valid_description(description)
    settings = {
        "reminder_interval_hours": defaults.reminder_interval_hours,
        "max_reminders": defaults.max_reminders,
        "expiry_days": defaults.expiry_days,
        "notify_emails": list(defaults.notify_emails),
        **_valid_settings(overrides or SettingsChange()),
    }
    try:
        with uow.session.begin_nested():  # a lost name race rolls back only this insert
            department_id = uow.session.execute(
                text(
                    "INSERT INTO departments (workspace_id, name, description, created_by, "
                    "reminder_interval_hours, max_reminders, expiry_days, notify_emails) "
                    "VALUES (:w, :n, :d, :u, :reminder_interval_hours, :max_reminders, "
                    ":expiry_days, :notify_emails) RETURNING id"
                ),
                {
                    "w": actor.workspace_id,
                    "n": clean_name,
                    "d": clean_description,
                    "u": actor.user_id,
                    **settings,
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
    settings: SettingsChange | None = None,
) -> DepartmentRow:
    current = _row(uow.session, actor.workspace_id, department_id)
    require_active(current)
    changes: dict[str, tuple[Any, Any]] = {}
    if name is not None and (new_name := _valid_name(name)) != current.name:
        changes["name"] = (current.name, new_name)
    if description is not None and (new_desc := _valid_description(description)) != (
        current.description
    ):
        changes["description"] = (current.description, new_desc)
    for field, value in _valid_settings(settings or SettingsChange()).items():
        if value != getattr(current, field):
            changes[field] = (getattr(current, field), value)
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
