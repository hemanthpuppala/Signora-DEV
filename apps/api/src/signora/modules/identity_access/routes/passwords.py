"""Forgot password, reset, and change password (Phase 2 LLD topic 2, §8.2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from signora.kernel.http import request_info
from signora.kernel.idempotency import IdempotencyGuard, idempotency_guard
from signora.modules.identity_access import passwords as password_service
from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.dependencies import (
    current_actor,
    database_of,
    limiter_of,
    settings_of,
)
from signora.modules.identity_access.domain.passwords import PasswordPolicy
from signora.modules.identity_access.routes.schemas import (
    AcceptedResponse,
    ChangePasswordRequest,
    EmailResponse,
    ResetRequest,
    SignupRequest,
    TokenRequest,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.post(
    "/auth/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset link",
)
def forgot(body: SignupRequest, request: Request) -> AcceptedResponse:
    """Always ``202``: "if an account exists for this email, you'll receive an email"."""
    with database_of(request).unit_of_work() as uow:
        password_service.request_reset(
            uow,
            limiter=limiter_of(request),
            settings=settings_of(request).auth,
            email=body.email,
            ip=request_info(request).ip,
        )
    return AcceptedResponse()


@router.post("/auth/password/reset/verify", summary="Check a reset link")
def verify(body: TokenRequest, request: Request) -> EmailResponse:
    with database_of(request).unit_of_work() as uow:
        return EmailResponse(email=password_service.verify_reset(uow, body.token))


@router.post(
    "/auth/password/reset",
    response_model=EmailResponse,
    summary="Set a new password with a reset link (requires Idempotency-Key)",
)
def reset(
    body: ResetRequest,
    request: Request,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    """Ends every session of the user; the page then sends them to log in."""
    settings = settings_of(request)
    with database_of(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        email = password_service.complete_reset(
            uow,
            policy=PasswordPolicy(min_length=settings.auth.password_min_length),
            token=body.token,
            password=body.password,
            base_url=str(settings.app.public_base_url),
        )
        return guard.finish(uow, status.HTTP_200_OK, {"email": email})


@router.post(
    "/me/password",
    response_model=AcceptedResponse,
    summary="Change your password (requires Idempotency-Key); other sessions end",
)
def change(
    body: ChangePasswordRequest,
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    settings = settings_of(request)
    with database_of(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        password_service.change_password(
            uow,
            actor=actor,
            limiter=limiter_of(request),
            settings=settings.auth,
            current_password=body.current_password,
            new_password=body.new_password,
            base_url=str(settings.app.public_base_url),
        )
        return guard.finish(uow, status.HTTP_200_OK, {"status": "changed"})
