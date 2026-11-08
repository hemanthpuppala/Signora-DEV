"""FastAPI dependencies of the identity module (Phase 2 LLD §4.2-4.3, §8.1).

``current_actor`` resolves the session cookie and, for state-changing requests, checks the signed
CSRF token (layer 2; layer 1 is the kernel's Origin check). Routes needing a permission declare
``Depends(require(Permission.X))``; nothing compares role names.

List ``actor`` before ``guard`` in a create endpoint's parameters: the idempotency guard scopes keys
by the actor that ``current_actor`` records on the request.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from fastapi import Request, Response

from signora.kernel.config import Settings
from signora.kernel.db import Database
from signora.kernel.errors import Unauthenticated
from signora.kernel.logging import bind_context
from signora.kernel.ratelimit import RateLimiter
from signora.modules.identity_access.access import Actor, authorize
from signora.modules.identity_access.domain.permissions import Permission
from signora.modules.identity_access.domain.tokens import csrf_matches, csrf_token, hash_token
from signora.modules.identity_access.errors import CsrfFailed
from signora.modules.identity_access.sessions import resolve_session

SESSION_COOKIE = "__Host-signora_session"
CSRF_COOKIE = "__Host-signora_csrf"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def database_of(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def limiter_of(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def _resolve(request: Request) -> Actor | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    auth = settings_of(request).auth
    with database_of(request).unit_of_work() as uow:
        return resolve_session(
            uow.session,
            hash_token(token),
            idle=timedelta(hours=auth.session_idle_hours),
            touch=timedelta(minutes=auth.session_touch_minutes),
        )


def _bind(request: Request, actor: Actor) -> None:
    request.state.actor_id = str(actor.user_id)
    bind_context(user_id=str(actor.user_id), workspace_id=str(actor.workspace_id))


def current_actor(request: Request) -> Actor:
    """The signed-in user, or ``401``. State-changing requests must carry the CSRF token."""
    actor = _resolve(request)
    if actor is None:
        raise Unauthenticated
    if request.method not in _SAFE_METHODS:
        secret = settings_of(request).app.secret_key.get_secret_value()
        if not csrf_matches(secret, actor.session_digest, request.headers.get(CSRF_HEADER)):
            raise CsrfFailed
    _bind(request, actor)
    return actor


def optional_actor(request: Request) -> Actor | None:
    """The signed-in user when there is one (no CSRF check: for idempotent reads and log-out)."""
    actor = _resolve(request)
    if actor is not None:
        _bind(request, actor)
    return actor


def require(permission: Permission) -> Callable[..., Actor]:
    """Dependency: the signed-in user, who must hold ``permission`` (``403`` otherwise)."""

    def dependency(request: Request) -> Actor:
        actor = current_actor(request)
        authorize(actor, permission)
        return actor

    dependency.__name__ = f"require_{permission.value.replace('.', '_')}"
    return dependency


def set_session_cookies(response: Response, request: Request, token: str) -> None:
    """Both cookies are host-only, HTTPS-only and browser-session scoped; the server enforces the
    idle limit. Only the CSRF cookie is readable by the page (it must echo it in a header)."""
    secret = settings_of(request).app.secret_key.get_secret_value()
    common = {"secure": True, "samesite": "lax", "path": "/"}
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token(secret, hash_token(token)),
        httponly=False,
        **common,  # type: ignore[arg-type]
    )


def clear_session_cookies(response: Response) -> None:
    for name, http_only in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(name, path="/", secure=True, httponly=http_only, samesite="lax")
