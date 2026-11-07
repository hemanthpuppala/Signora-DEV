"""HTTP plumbing shared by every module's router (backbone LLD §7.1 to §7.2).

- ``RequestContextMiddleware`` assigns the request id, binds log context, records the client IP and
  user agent, writes one access line per request with the *route template* (never the raw path,
  which may contain signing tokens), and turns any unhandled exception into a generic 500 problem.
- ``install_error_handlers`` maps domain errors, validation errors and routing errors to RFC 9457
  problem details with a stable ``code``.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from signora.kernel.context import Origin, set_origin
from signora.kernel.errors import DomainError, FieldError, ValidationFailed
from signora.kernel.logging import bind_context, clear_context, current_context, get_logger

PROBLEM_MEDIA_TYPE = "application/problem+json"
REQUEST_ID_HEADER = "X-Request-ID"
# Accept only plain ids from the proxy (Caddy sends a UUID); anything else is replaced.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
_USER_AGENT_MAX = 512

log = get_logger("signora.http")


@dataclass(frozen=True)
class RequestInfo:
    """Who is calling, for audit entries and logs."""

    request_id: str
    ip: str | None
    user_agent: str | None


def request_info(request: Request) -> RequestInfo:
    state = request.scope.get("state", {})
    return RequestInfo(
        request_id=state.get("request_id", ""),
        ip=state.get("client_ip"),
        user_agent=state.get("user_agent"),
    )


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "<unmatched>"


def problem_body(
    *,
    code: str,
    title: str,
    status: int,
    detail: str | None,
    instance: str,
    request_id: str | None,
    errors: Sequence[FieldError] = (),
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"/problems/{code}",
        "title": title,
        "status": status,
        "code": code,
        "instance": instance,
        "request_id": request_id,
    }
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = [{"field": e.field, "message": e.message} for e in errors]
    return body


def problem_response(
    request: Request,
    *,
    code: str,
    title: str,
    status: int,
    detail: str | None = None,
    errors: Sequence[FieldError] = (),
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = problem_body(
        code=code,
        title=title,
        status=status,
        detail=detail,
        instance=_route_template(request.scope),
        request_id=request_info(request).request_id or None,
        errors=errors,
    )
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_MEDIA_TYPE)


class RequestContextMiddleware:
    """Pure ASGI middleware (no BaseHTTPMiddleware: keeps streaming and context intact)."""

    def __init__(self, app: ASGIApp, *, trust_proxy_headers: bool) -> None:
        self.app = app
        self.trust_proxy_headers = trust_proxy_headers

    def _request_id(self, headers: Headers) -> str:
        incoming = headers.get(REQUEST_ID_HEADER)
        if self.trust_proxy_headers and incoming and _REQUEST_ID_PATTERN.match(incoming):
            return incoming
        return str(uuid.uuid4())

    def _client_ip(self, scope: Scope, headers: Headers) -> str | None:
        if self.trust_proxy_headers:
            forwarded = headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip() or None
        client = scope.get("client")
        return client[0] if client else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = self._request_id(headers)
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["client_ip"] = self._client_ip(scope, headers)
        user_agent = headers.get("user-agent")
        state["user_agent"] = user_agent[:_USER_AGENT_MAX] if user_agent else None

        clear_context()
        bind_context(request_id=request_id)
        set_origin(Origin(request_id, state["client_ip"], state["user_agent"]))
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            log.exception("http.unhandled_error", route=_route_template(scope))
            if not response_started:
                body = problem_body(
                    code="internal-error",
                    title="Something went wrong on our side",
                    status=500,
                    detail=None,
                    instance=_route_template(scope),
                    request_id=request_id,
                )
                response = JSONResponse(body, status_code=500, media_type=PROBLEM_MEDIA_TYPE)
                await response(scope, receive, send_with_request_id)
            status = 500
        finally:
            log.info(
                "http.request",
                method=scope["method"],
                route=_route_template(scope),
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                **{k: v for k, v in current_context().items() if k != "request_id"},
            )
            clear_context()
            set_origin(None)


def _field_path(location: Sequence[int | str]) -> str:
    parts = list(location)
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:]
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path or "request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, error: DomainError) -> JSONResponse:
        return problem_response(
            request,
            code=error.code,
            title=error.title,
            status=error.status,
            detail=error.detail,
            errors=error.field_errors,
            headers=dict(error.headers),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        field_errors = [
            FieldError(_field_path(item.get("loc", ())), str(item.get("msg", "Invalid value")))
            for item in error.errors()
        ]
        return await _domain_error(request, ValidationFailed(field_errors))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        codes = {404: ("not-found", "Not found"), 405: ("method-not-allowed", "Method not allowed")}
        code, title = codes.get(error.status_code, ("http-error", "The request failed"))
        return problem_response(
            request,
            code=code,
            title=title,
            status=error.status_code,
            headers=dict(error.headers) if error.headers else None,
        )
