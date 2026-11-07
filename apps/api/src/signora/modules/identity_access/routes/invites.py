"""Invites (Phase 2 LLD topic 6). Managing them needs ``members.manage``; accepting is public."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from signora.kernel.idempotency import IdempotencyGuard, idempotency_guard
from signora.modules.identity_access import invites as invite_service
from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.dependencies import (
    database_of,
    limiter_of,
    require,
    settings_of,
)
from signora.modules.identity_access.domain.passwords import PasswordPolicy
from signora.modules.identity_access.domain.permissions import Permission
from signora.modules.identity_access.routes.schemas import (
    AcceptInviteRequest,
    EmailResponse,
    InviteDetailsView,
    InviteRequest,
    InviteView,
    RoleRef,
    TokenRequest,
)

router = APIRouter(prefix="/api/v1/invites", tags=["invites"])
Manager = Annotated[Actor, Depends(require(Permission.MEMBERS_MANAGE))]


def view(row: invite_service.InviteRow) -> InviteView:
    return InviteView(
        id=row.id,
        email=row.email,
        role=RoleRef(id=row.role_id, name=row.role_name),
        invited_by_name=row.invited_by_name,
        created_at=row.created_at,
        expires_at=row.expires_at,
        expired=row.expired,
    )


@router.get("", summary="Pending invitations")
def list_invites(request: Request, actor: Manager) -> list[InviteView]:
    with database_of(request).unit_of_work() as uow:
        return [view(row) for row in invite_service.list_pending(uow.session, actor.workspace_id)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=InviteView,
    summary="Invite someone by email (requires Idempotency-Key)",
)
def create_invite(
    body: InviteRequest,
    request: Request,
    actor: Manager,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    settings = settings_of(request)
    with database_of(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        row = invite_service.create_invite(
            uow,
            actor=actor,
            limiter=limiter_of(request),
            settings=settings.auth,
            email=body.email,
            role_id=body.role_id,
            base_url=str(settings.app.public_base_url),
        )
        return guard.finish(uow, status.HTTP_201_CREATED, view(row).model_dump(mode="json"))


@router.post(
    "/{invite_id}/resend",
    response_model=InviteView,
    summary="Send a new link; the old one stops working (requires Idempotency-Key)",
)
def resend_invite(
    invite_id: uuid.UUID,
    request: Request,
    actor: Manager,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    settings = settings_of(request)
    with database_of(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        row = invite_service.resend_invite(
            uow,
            actor=actor,
            limiter=limiter_of(request),
            settings=settings.auth,
            invite_id=invite_id,
            base_url=str(settings.app.public_base_url),
        )
        return guard.finish(uow, status.HTTP_200_OK, view(row).model_dump(mode="json"))


@router.delete(
    "/{invite_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke an invitation"
)
def revoke_invite(invite_id: uuid.UUID, request: Request, actor: Manager) -> None:
    with database_of(request).unit_of_work() as uow:
        invite_service.revoke_invite(uow, actor=actor, invite_id=invite_id)


@router.post("/verify", summary="Check an invitation link")
def verify_invite(body: TokenRequest, request: Request) -> InviteDetailsView:
    with database_of(request).unit_of_work() as uow:
        details = invite_service.verify_invite(uow, body.token)
    return InviteDetailsView(
        email=details.email,
        workspace_name=details.workspace_name,
        role_name=details.role_name,
        inviter_name=details.inviter_name,
    )


@router.post(
    "/accept",
    status_code=status.HTTP_201_CREATED,
    response_model=EmailResponse,
    summary="Accept an invitation (requires Idempotency-Key); the page logs in next",
)
def accept_invite(
    body: AcceptInviteRequest,
    request: Request,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    policy = PasswordPolicy(min_length=settings_of(request).auth.password_min_length)
    with database_of(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        email = invite_service.accept_invite(
            uow, policy=policy, token=body.token, name=body.name, password=body.password
        )
        return guard.finish(uow, status.HTTP_201_CREATED, {"email": email})
