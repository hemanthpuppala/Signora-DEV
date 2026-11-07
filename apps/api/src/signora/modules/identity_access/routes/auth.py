"""Log-in, log-out and the current user (Phase 2 LLD topic 7, §8.2). Handlers are plain ``def``."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from signora.kernel.http import request_info
from signora.kernel.logging import get_logger
from signora.modules.identity_access import login as login_service
from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.dependencies import (
    SESSION_COOKIE,
    clear_session_cookies,
    current_actor,
    database_of,
    limiter_of,
    optional_actor,
    set_session_cookies,
    settings_of,
)
from signora.modules.identity_access.domain.tokens import hash_token
from signora.modules.identity_access.routes.schemas import LoginRequest, MeResponse
from signora.modules.identity_access.sessions import delete_session, resolve_session

router = APIRouter(prefix="/api/v1", tags=["auth"])
security = get_logger("signora.security")


@router.post("/auth/login", summary="Log in")
def log_in(body: LoginRequest, request: Request, response: Response) -> MeResponse:
    info = request_info(request)
    settings = settings_of(request)
    with database_of(request).unit_of_work() as uow:
        result = login_service.login(
            uow,
            limiter=limiter_of(request),
            settings=settings.auth,
            email=body.email,
            password=body.password,
            ip=info.ip,
            user_agent=info.user_agent,
        )
        actor = resolve_session(
            uow.session,
            result.token.digest,
            idle=timedelta(hours=settings.auth.session_idle_hours),
            touch=timedelta(minutes=settings.auth.session_touch_minutes),
        )
    if actor is None:  # pragma: no cover - the session was created in this transaction
        raise RuntimeError("new session did not resolve")
    set_session_cookies(response, request, result.token.value)
    return MeResponse.of(actor)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Log out")
def log_out(
    request: Request, response: Response, actor: Annotated[Actor | None, Depends(optional_actor)]
) -> None:
    """Ends the session on the server and clears the cookies; succeeds when already signed out."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with database_of(request).unit_of_work() as uow:
            delete_session(uow.session, hash_token(token))
    if actor is not None:
        security.info("auth.logout", user_id=str(actor.user_id))
    clear_session_cookies(response)


@router.get("/me", summary="The signed-in user, workspace, role and permissions")
def me(actor: Annotated[Actor, Depends(current_actor)]) -> MeResponse:
    return MeResponse.of(actor)
