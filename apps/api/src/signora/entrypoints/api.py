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
from typing import Any

import anyio.to_thread
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from signora.kernel.config import Settings, get_settings
from signora.kernel.db import Database, create_db_engine
from signora.kernel.health import Check, core_checks, integration_results, run_checks
from signora.kernel.http import RequestContextMiddleware, install_error_handlers
from signora.kernel.logging import configure_logging

API_PREFIX = "/api/v1"
INTERNAL_PREFIX = "/internal"  # never forwarded by Caddy (LLD §7.3)

ChecksFactory = Callable[[Settings, Engine], Sequence[Check]]


def _health_router() -> APIRouter:
    router = APIRouter()

    @router.get(f"{API_PREFIX}/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get(f"{API_PREFIX}/health/ready", tags=["health"])
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
    def meta(request: Request) -> dict[str, str]:
        settings: Settings = request.app.state.settings
        return {"version": version("signora"), "commit": settings.app.commit}

    return router


def create_app(
    settings: Settings,
    *,
    engine: Engine | None = None,
    checks_factory: ChecksFactory = core_checks,
) -> FastAPI:
    """Build the application. Tests pass their own engine and readiness checks."""
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
    )
    app.state.settings = settings
    app.state.engine = app_engine
    app.state.database = Database(app_engine)
    app.state.checks = lambda: checks_factory(settings, app_engine)

    install_error_handlers(app)
    app.add_middleware(
        RequestContextMiddleware, trust_proxy_headers=settings.api.trust_proxy_headers
    )
    app.include_router(_health_router())
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory`` and ``signora api``."""
    settings = get_settings()
    configure_logging(settings.app)
    return create_app(settings)
