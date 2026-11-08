"""FastAPI application factory (backbone LLD §7.3, §6.3a).

Business modules add their routers here as they arrive. Database-touching handlers are plain
``def`` functions, which FastAPI runs in its thread pool; that pool is capped at ``API_THREADS`` and
the connection pool matches it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib.metadata import version
from typing import Any, Literal

import anyio.to_thread
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine

from signora.handlers import register_all
from signora.kernel.blobstore import blob_store_from_settings
from signora.kernel.config import Settings, get_settings
from signora.kernel.db import Database, create_db_engine
from signora.kernel.health import Check, core_checks, integration_results, run_checks
from signora.kernel.http import (
    PROBLEM_RESPONSES,
    OriginCheckMiddleware,
    RequestContextMiddleware,
    install_error_handlers,
    origin_of,
)
from signora.kernel.jobs import registry
from signora.kernel.logging import configure_logging
from signora.kernel.ratelimit import create_rate_limiter
from signora.modules import departments, documents, identity_access

API_PREFIX = "/api/v1"
INTERNAL_PREFIX = "/internal"  # never forwarded by Caddy (LLD §7.3)

ChecksFactory = Callable[[Settings, Engine], Sequence[Check]]


class StatusResponse(BaseModel):
    status: Literal["ok", "unavailable"]


class MetaResponse(BaseModel):
    version: str
    commit: str
    password_min_length: int
    password_rule: str  # the server's own wording of the rule, shown as the form hint
    document_max_bytes: int  # upload limits (Phase 4 LLD §2.1), shown before uploading
    document_max_pages: int


def _health_router() -> APIRouter:
    router = APIRouter()

    @router.get(f"{API_PREFIX}/health/live", tags=["health"])
    def live() -> StatusResponse:
        return StatusResponse(status="ok")

    @router.get(
        f"{API_PREFIX}/health/ready",
        tags=["health"],
        response_model=StatusResponse,
        responses={503: {"model": StatusResponse, "description": "Not ready"}},
    )
    def ready(request: Request) -> JSONResponse:
        readiness = run_checks(request.app.state.checks())
        status = "ok" if readiness.ready else "unavailable"
        return JSONResponse({"status": status}, status_code=200 if readiness.ready else 503)

    @router.get(f"{INTERNAL_PREFIX}/health/ready", include_in_schema=False)
    def ready_detail(request: Request) -> JSONResponse:
        readiness = run_checks(request.app.state.checks())
        settings: Settings = request.app.state.settings
        checks = [asdict(r) for r in (*readiness.checks, *integration_results(settings))]
        body: dict[str, Any] = {
            "status": "ok" if readiness.ready else "unavailable",
            "checks": checks,
        }
        return JSONResponse(body, status_code=200 if readiness.ready else 503)

    @router.get(f"{API_PREFIX}/meta", tags=["meta"])
    def meta(request: Request) -> MetaResponse:
        settings: Settings = request.app.state.settings
        return MetaResponse(
            version=version("signora"),
            commit=settings.app.commit,
            password_min_length=settings.auth.password_min_length,
            password_rule=identity_access.PasswordPolicy(settings.auth.password_min_length).rule,
            document_max_bytes=settings.documents.max_bytes,
            document_max_pages=settings.documents.max_pages,
        )

    return router


def create_app(
    settings: Settings,
    *,
    engine: Engine | None = None,
    checks_factory: ChecksFactory = core_checks,
) -> FastAPI:
    """Build the application. Tests pass their own engine and readiness checks."""
    # The API enqueues jobs, so it knows the same job kinds as the worker (handlers.py).
    register_all(registry)
    owns_engine = engine is None
    app_engine = engine or create_db_engine(settings.db, pool_size=settings.api.threads)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        anyio.to_thread.current_default_thread_limiter().total_tokens = settings.api.threads
        yield
        if owns_engine:
            app_engine.dispose()

    show_docs = not settings.app.is_production
    app = FastAPI(
        title="Signora API",
        version=version("signora"),
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs" if show_docs else None,
        redoc_url=None,
        responses=PROBLEM_RESPONSES,
    )
    app.state.settings = settings
    app.state.engine = app_engine
    app.state.database = Database(app_engine)
    app.state.checks = lambda: checks_factory(settings, app_engine)
    app.state.rate_limiter = create_rate_limiter(settings.rate_limit)
    app.state.blob_store = blob_store_from_settings(settings.blob_store)

    install_error_handlers(app)
    # Added last = outermost: the request context (request id, access log) wraps the origin check.
    app.add_middleware(
        OriginCheckMiddleware, public_origin=origin_of(str(settings.app.public_base_url))
    )
    app.add_middleware(
        RequestContextMiddleware, trust_proxy_headers=settings.api.trust_proxy_headers
    )
    app.include_router(_health_router())
    app.include_router(identity_access.router)
    app.include_router(departments.router)
    app.include_router(documents.router)
    # A removed member leaves every countersigner list and loses every department grant, in the
    # removal's own transaction.
    identity_access.on_member_removed(departments.drop_removed_member)
    identity_access.on_member_removed(departments.revoke_removed_member)
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory`` and ``signora api``."""
    settings = get_settings()
    configure_logging(settings.app)
    return create_app(settings)
