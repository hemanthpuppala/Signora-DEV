"""People, roles, workspace and profile (Phase 2 LLD §8.2)."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from signora.modules.identity_access import members as member_service
from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.dependencies import current_actor, database_of, require
from signora.modules.identity_access.domain.permissions import Permission
from signora.modules.identity_access.routes.schemas import (
    ChangeRoleRequest,
    DirectoryEntryView,
    DisplayRole,
    MemberView,
    MeResponse,
    NameRequest,
    RoleDetailView,
    RoleRef,
    WorkspaceView,
)

router = APIRouter(prefix="/api/v1", tags=["members"])
Manager = Annotated[Actor, Depends(require(Permission.MEMBERS_MANAGE))]


def view(row: member_service.MemberRow) -> MemberView:
    return MemberView(
        id=row.id,
        name=row.name,
        email=row.email,
        role=RoleRef(id=row.role_id, name=row.role_name, description=row.role_description),
        display_role=DisplayRole.of(
            is_creator=row.is_creator, name=row.role_name, description=row.role_description
        ),
        is_creator=row.is_creator,
        joined_at=row.joined_at,
    )


@router.get("/members", summary="Members with their roles (People screen)")
def list_members(request: Request, actor: Manager) -> list[MemberView]:
    with database_of(request).unit_of_work() as uow:
        return [view(r) for r in member_service.list_members(uow.session, actor.workspace_id)]


@router.get("/members/directory", summary="Active colleagues for pickers")
def directory(
    request: Request,
    actor: Annotated[Actor, Depends(require(Permission.MEMBERS_DIRECTORY))],
) -> list[DirectoryEntryView]:
    with database_of(request).unit_of_work() as uow:
        entries = member_service.directory(uow.session, actor.workspace_id)
    return [DirectoryEntryView(id=e.id, name=e.name, email=e.email) for e in entries]


@router.get("/roles", summary="The workspace's roles")
def list_roles(request: Request, actor: Manager) -> list[RoleDetailView]:
    with database_of(request).unit_of_work() as uow:
        roles = member_service.list_roles(uow.session, actor.workspace_id)
    return [RoleDetailView(**dataclasses.asdict(role)) for role in roles]


@router.patch("/members/{user_id}", summary="Change a member's role")
def change_role(
    user_id: uuid.UUID, body: ChangeRoleRequest, request: Request, actor: Manager
) -> MemberView:
    with database_of(request).unit_of_work() as uow:
        row = member_service.change_role(uow, actor=actor, user_id=user_id, role_id=body.role_id)
    return view(row)


@router.delete(
    "/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member (their sessions end at once)",
)
def remove_member(user_id: uuid.UUID, request: Request, actor: Manager) -> None:
    with database_of(request).unit_of_work() as uow:
        member_service.remove_member(uow, actor=actor, user_id=user_id)


@router.patch("/workspace", summary="Rename the workspace")
def rename_workspace(
    body: NameRequest,
    request: Request,
    actor: Annotated[Actor, Depends(require(Permission.WORKSPACE_RENAME))],
) -> WorkspaceView:
    with database_of(request).unit_of_work() as uow:
        name = member_service.rename_workspace(uow, actor=actor, name=body.name)
    return WorkspaceView(id=actor.workspace_id, name=name)


@router.patch("/me", summary="Change your name")
def rename_self(
    body: NameRequest, request: Request, actor: Annotated[Actor, Depends(current_actor)]
) -> MeResponse:
    with database_of(request).unit_of_work() as uow:
        member_service.rename_self(uow, actor=actor, name=body.name)
    return MeResponse.of(dataclasses.replace(actor, name=body.name))
