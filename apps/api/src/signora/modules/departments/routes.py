"""Department endpoints (Phase 3 LLD §1.5). Handlers are plain ``def``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from signora.kernel.db import Database
from signora.kernel.idempotency import IdempotencyGuard, idempotency_guard
from signora.modules.departments import service
from signora.modules.identity_access import Actor, Permission, current_actor, require

router = APIRouter(prefix="/api/v1/departments", tags=["departments"])

# Lengths are checked after normalising (domain.py); these bounds only stop oversized bodies.
NameInput = Annotated[str, StringConstraints(max_length=200)]
DescriptionInput = Annotated[str, StringConstraints(max_length=2000)]
EmailText = Annotated[str, StringConstraints(max_length=320)]
Creator = Annotated[Actor, Depends(require(Permission.DEPARTMENTS_CREATE))]
Manager = Annotated[Actor, Depends(require(Permission.DEPARTMENTS_MANAGE))]
Member = Annotated[Actor, Depends(current_actor)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsInput(_Body):
    reminder_interval_hours: int | None = None
    max_reminders: int | None = None
    expiry_days: int | None = None
    notify_emails: Annotated[list[EmailText], Field(max_length=20)] | None = None

    def change(self) -> service.SettingsChange:
        return service.SettingsChange(**self.model_dump())


class CreateDepartment(_Body):
    name: NameInput
    description: DescriptionInput = ""
    settings: SettingsInput | None = None  # overrides of the company defaults


class UpdateDepartment(_Body):
    name: NameInput | None = None
    description: DescriptionInput | None = None
    settings: SettingsInput | None = None


class DepartmentSettings(BaseModel):
    reminder_interval_hours: int
    max_reminders: int
    expiry_days: int
    notify_emails: list[str]


class PersonRef(BaseModel):
    id: uuid.UUID
    name: str


class Counts(BaseModel):
    sent: int = 0
    signed: int = 0
    pending: int = 0


class DepartmentSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    status: Literal["active", "archived"]
    created_at: datetime
    counts: Counts  # counts of sends; zeros until sends exist (Phase 7)


class Department(DepartmentSummary):
    updated_at: datetime
    archived_at: datetime | None
    created_by: PersonRef
    settings: DepartmentSettings


def summary(row: service.DepartmentRow) -> DepartmentSummary:
    return DepartmentSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        created_at=row.created_at,
        counts=Counts(),
    )


def detail(row: service.DepartmentRow) -> Department:
    return Department(
        **summary(row).model_dump(),
        updated_at=row.updated_at,
        archived_at=row.archived_at,
        created_by=PersonRef(id=row.created_by_id, name=row.created_by_name),
        settings=DepartmentSettings(
            reminder_interval_hours=row.reminder_interval_hours,
            max_reminders=row.max_reminders,
            expiry_days=row.expiry_days,
            notify_emails=row.notify_emails,
        ),
    )


def company_defaults(request: Request) -> service.Settings:
    """The company defaults from configuration (``DEFAULT_*`` in ``.env``)."""
    signing = request.app.state.settings.signing
    return service.Settings(
        reminder_interval_hours=signing.default_reminder_interval_hours,
        max_reminders=signing.default_max_reminders,
        expiry_days=signing.default_expiry_days,
        notify_emails=(),
    )


def _db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


@router.get("", summary="Departments of the company, sorted by name")
def list_departments(
    request: Request,
    actor: Member,
    status_filter: Annotated[Literal["active", "archived"], Query(alias="status")] = "active",
) -> list[DepartmentSummary]:
    with _db(request).unit_of_work() as uow:
        rows = service.list_departments(uow.session, actor.workspace_id, status_filter)
    return [summary(row) for row in rows]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Department,
    summary="Create a department (requires Idempotency-Key)",
)
def create_department(
    body: CreateDepartment,
    request: Request,
    actor: Creator,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    with _db(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        row = service.create_department(
            uow,
            actor=actor,
            name=body.name,
            description=body.description,
            defaults=company_defaults(request),
            overrides=body.settings.change() if body.settings else None,
        )
        return guard.finish(uow, status.HTTP_201_CREATED, detail(row).model_dump(mode="json"))


@router.get("/{department_id}", summary="One department")
def get_department(department_id: uuid.UUID, request: Request, actor: Member) -> Department:
    with _db(request).unit_of_work() as uow:
        return detail(service.get_department(uow.session, actor.workspace_id, department_id))


@router.patch("/{department_id}", summary="Rename or describe a department")
def update_department(
    department_id: uuid.UUID, body: UpdateDepartment, request: Request, actor: Manager
) -> Department:
    with _db(request).unit_of_work() as uow:
        row = service.update_department(
            uow,
            actor=actor,
            department_id=department_id,
            name=body.name,
            description=body.description,
            settings=body.settings.change() if body.settings else None,
        )
    return detail(row)


@router.post("/{department_id}/archive", summary="Archive a department (repeat-safe)")
def archive_department(department_id: uuid.UUID, request: Request, actor: Manager) -> Department:
    with _db(request).unit_of_work() as uow:
        return detail(service.archive_department(uow, actor=actor, department_id=department_id))


@router.post("/{department_id}/restore", summary="Restore an archived department (repeat-safe)")
def restore_department(department_id: uuid.UUID, request: Request, actor: Manager) -> Department:
    with _db(request).unit_of_work() as uow:
        return detail(service.restore_department(uow, actor=actor, department_id=department_id))
