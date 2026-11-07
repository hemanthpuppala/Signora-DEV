"""Email-first sign-up (Phase 2 LLD topic 1). Handlers are plain ``def``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from signora.kernel.http import request_info
from signora.kernel.idempotency import IdempotencyGuard, idempotency_guard
from signora.modules.identity_access import signup as signup_service
from signora.modules.identity_access.dependencies import database_of, limiter_of, settings_of
from signora.modules.identity_access.domain.passwords import PasswordPolicy
from signora.modules.identity_access.routes.schemas import (
    AcceptedResponse,
    EmailResponse,
    SignupCompleteRequest,
    SignupRequest,
    TokenRequest,
)

router = APIRouter(prefix="/api/v1/auth/signup", tags=["auth"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, summary="Start sign-up with an email")
def start(body: SignupRequest, request: Request) -> AcceptedResponse:
    """Always ``202``: the email says what happens next (verify, or log in if registered)."""
    settings = settings_of(request)
    with database_of(request).unit_of_work() as uow:
        signup_service.request_signup(
            uow,
            limiter=limiter_of(request),
            settings=settings.auth,
            email=body.email,
            ip=request_info(request).ip,
        )
    return AcceptedResponse()


@router.post("/verify", summary="Check a sign-up link")
def verify(body: TokenRequest, request: Request) -> EmailResponse:
    with database_of(request).unit_of_work() as uow:
        return EmailResponse(email=signup_service.verify_signup(uow, body.token))


@router.post(
    "/complete",
    status_code=status.HTTP_201_CREATED,
    response_model=EmailResponse,
    summary="Create the workspace and its creator (requires Idempotency-Key)",
)
def complete(
    body: SignupCompleteRequest,
    request: Request,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    """No session is set here; the page logs in with the new password next."""
    policy = PasswordPolicy(min_length=settings_of(request).auth.password_min_length)
    with database_of(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        email = signup_service.complete_signup(
            uow,
            policy=policy,
            token=body.token,
            workspace_name=body.workspace_name,
            name=body.name,
            password=body.password,
        )
        return guard.finish(uow, status.HTTP_201_CREATED, {"email": email})
