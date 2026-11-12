"""People, roles, workspace and profile (Phase 2 LLD §8.2)."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse

from signora.kernel.blobstore import BlobNotFoundError, BlobStore
from signora.kernel.errors import NotFound
from signora.modules.identity_access import company_logo
from signora.modules.identity_access import members as member_service
from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.dependencies import (
    current_actor,
    database_of,
    require,
    settings_of,
)
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
    WebsiteRequest,
    WorkspaceView,
)
from signora.modules.identity_access.signup import valid_website

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
    return WorkspaceView.of(actor, name=name)


@router.put("/workspace/website", summary="Set or remove the company's website (owner only)")
def change_website(
    body: WebsiteRequest, request: Request, actor: Annotated[Actor, Depends(current_actor)]
) -> WorkspaceView:
    domain = valid_website(body.website)
    with database_of(request).unit_of_work() as uow:
        logo = member_service.change_website(
            uow, actor=actor, domain=domain, queue=settings_of(request).logo.configured
        )
    # A known domain's logo shows at once; a new one once it is found.
    return WorkspaceView.of(
        dataclasses.replace(actor, workspace_website=domain, workspace_logo=logo)
    )


@router.get(
    "/workspace/logo",
    summary="The company's logo (PNG), for its members' header",
    response_class=FileResponse,
)
def workspace_logo(
    request: Request, actor: Annotated[Actor, Depends(current_actor)]
) -> FileResponse:
    """Addressed with the logo's hash (``WorkspaceView.logo_url``), so a browser keeps it until
    the logo changes. A file missing from the store is fetched again; the name shows meanwhile."""
    with database_of(request).unit_of_work() as uow:
        found = company_logo.logo_of(uow.session, actor.workspace_id)
        if found is None:
            raise NotFound("This company has no logo")
        domain, logo = found
        store: BlobStore = request.app.state.blob_store
        try:
            path = store.path(logo)
        except BlobNotFoundError:
            company_logo.forget_missing(
                uow.session, domain, logo, queue=settings_of(request).logo.configured
            )
            path = None
    if path is None:
        raise NotFound("This company has no logo")
    return FileResponse(
        path,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch("/me", summary="Change your name")
def rename_self(
    body: NameRequest, request: Request, actor: Annotated[Actor, Depends(current_actor)]
) -> MeResponse:
    with database_of(request).unit_of_work() as uow:
        member_service.rename_self(uow, actor=actor, name=body.name)
    return MeResponse.of(dataclasses.replace(actor, name=body.name))
