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
from signora.modules.departments import access as grants
from signora.modules.departments import service
from signora.modules.departments.access import DepartmentAccess, GrantRow, load_access
from signora.modules.departments.countersigners import (
    Countersigner,
    list_countersigners,
    set_countersigners,
)
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
    access: Literal["edit", "read"]  # the caller's access in this department (topic 2)


class CountersignerView(BaseModel):
    id: uuid.UUID
    name: str
    email: str


class Department(DepartmentSummary):
    updated_at: datetime
    archived_at: datetime | None
    created_by: PersonRef
    settings: DepartmentSettings
    countersigners: list[CountersignerView]  # who may countersign, in default order


def summary(row: service.DepartmentRow, rights: DepartmentAccess) -> DepartmentSummary:
    return DepartmentSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        created_at=row.created_at,
        counts=Counts(),
        access=rights.level(row.id),
    )


def detail(
    row: service.DepartmentRow, rights: DepartmentAccess, signers: list[Countersigner]
) -> Department:
    return Department(
        **summary(row, rights).model_dump(),
        countersigners=[CountersignerView(id=s.id, name=s.name, email=s.email) for s in signers],
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
        rights = load_access(uow.session, actor)
    return [summary(row, rights) for row in rows]


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
        created = detail(
            row,
            load_access(uow.session, actor),
            list_countersigners(uow.session, actor.workspace_id, row.id),
        ).model_dump(mode="json")
        return guard.finish(uow, status.HTTP_201_CREATED, created)


@router.get("/{department_id}", summary="One department")
def get_department(department_id: uuid.UUID, request: Request, actor: Member) -> Department:
    with _db(request).unit_of_work() as uow:
        row = service.get_department(uow.session, actor.workspace_id, department_id)
        return detail(
            row,
            load_access(uow.session, actor),
            list_countersigners(uow.session, actor.workspace_id, row.id),
        )


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
        return detail(
            row,
            load_access(uow.session, actor),
            list_countersigners(uow.session, actor.workspace_id, row.id),
        )


@router.post("/{department_id}/archive", summary="Archive a department (repeat-safe)")
def archive_department(department_id: uuid.UUID, request: Request, actor: Manager) -> Department:
    with _db(request).unit_of_work() as uow:
        row = service.archive_department(uow, actor=actor, department_id=department_id)
        return detail(
            row,
            load_access(uow.session, actor),
            list_countersigners(uow.session, actor.workspace_id, row.id),
        )


@router.post("/{department_id}/restore", summary="Restore an archived department (repeat-safe)")
def restore_department(department_id: uuid.UUID, request: Request, actor: Manager) -> Department:
    with _db(request).unit_of_work() as uow:
        row = service.restore_department(uow, actor=actor, department_id=department_id)
        return detail(
            row,
            load_access(uow.session, actor),
            list_countersigners(uow.session, actor.workspace_id, row.id),
        )


class GrantsInput(_Body):
    user_ids: Annotated[list[uuid.UUID], Field(max_length=1000)]


class Grant(BaseModel):
    user: PersonRef
    email: str
    granted_by: PersonRef
    created_at: datetime


def grant_views(rows: list[GrantRow]) -> list[Grant]:
    return [
        Grant(
            user=PersonRef(id=row.user_id, name=row.user_name),
            email=row.user_email,
            granted_by=PersonRef(id=row.granted_by_id, name=row.granted_by_name),
            created_at=row.created_at,
        )
        for row in rows
    ]


PeopleManager = Annotated[Actor, Depends(require(Permission.MEMBERS_MANAGE))]


@router.get("/{department_id}/grants", summary="People with edit access in this department")
def list_grants(department_id: uuid.UUID, request: Request, actor: PeopleManager) -> list[Grant]:
    with _db(request).unit_of_work() as uow:
        return grant_views(grants.list_grants(uow.session, actor.workspace_id, department_id))


@router.get(
    "/{department_id}/grants/candidates",
    summary="Members a grant would help: not the creator, not roles that edit everywhere",
)
def list_grant_candidates(
    department_id: uuid.UUID, request: Request, actor: PeopleManager
) -> list[CountersignerView]:
    with _db(request).unit_of_work() as uow:
        people = grants.grant_candidates(uow.session, actor.workspace_id, department_id)
    return [CountersignerView(id=p.id, name=p.name, email=p.email) for p in people]


@router.put(
    "/{department_id}/grants",
    summary="Replace who has edit access in this department (repeat-safe)",
)
def set_grants(
    department_id: uuid.UUID, body: GrantsInput, request: Request, actor: PeopleManager
) -> list[Grant]:
    with _db(request).unit_of_work() as uow:
        rows = grants.set_grants(
            uow, actor=actor, department_id=department_id, user_ids=body.user_ids
        )
    return grant_views(rows)


class CountersignersInput(_Body):
    user_ids: Annotated[list[uuid.UUID], Field(max_length=1000)]


@router.put(
    "/{department_id}/countersigners",
    summary="Replace who may countersign, in default order (repeat-safe)",
)
def replace_countersigners(
    department_id: uuid.UUID, body: CountersignersInput, request: Request, actor: Manager
) -> list[CountersignerView]:
    with _db(request).unit_of_work() as uow:
        signers = set_countersigners(
            uow, actor=actor, department_id=department_id, user_ids=body.user_ids
        )
    return [CountersignerView(id=s.id, name=s.name, email=s.email) for s in signers]
