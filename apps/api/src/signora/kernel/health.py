"""Readiness checks (backbone LLD §7.3).

Each check has a 2-second limit and the checks run concurrently. Core checks decide readiness;
integration checks are informational ("configured" or "not configured").
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from sqlalchemy import Engine, text

from signora.kernel.config import DatabaseSettings, Settings
from signora.kernel.migrations import migrations_at_head

CHECK_TIMEOUT_SECONDS = 2.0

CheckStatus = Literal["ok", "failed", "not_configured", "configured"]


class CheckFailedError(Exception):
    """Raised by a check with a short, non-sensitive reason."""


@dataclass(frozen=True)
class Check:
    name: str
    run: Callable[[], None]  # raises on failure
    core: bool = True


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    core: bool
    duration_ms: int
    message: str | None = None


@dataclass(frozen=True)
class Readiness:
    ready: bool
    checks: tuple[CheckResult, ...]


def run_checks(checks: Sequence[Check], timeout: float = CHECK_TIMEOUT_SECONDS) -> Readiness:
    """Run all checks concurrently; a check that exceeds ``timeout`` counts as failed."""
    results: list[CheckResult] = []
    with ThreadPoolExecutor(max_workers=max(len(checks), 1)) as pool:
        started = time.monotonic()
        futures = [(check, pool.submit(check.run)) for check in checks]
        for check, future in futures:
            remaining = max(timeout - (time.monotonic() - started), 0.0)
            try:
                future.result(timeout=remaining)
                status: CheckStatus = "ok"
                message = None
            except FutureTimeout:
                status, message = "failed", f"timed out after {timeout:g} s"
            except CheckFailedError as error:
                status, message = "failed", str(error)
            except Exception as error:  # reported as a failed check, never raised
                status, message = "failed", type(error).__name__
            elapsed = int((time.monotonic() - started) * 1000)
            results.append(CheckResult(check.name, status, check.core, elapsed, message))
        pool.shutdown(wait=False, cancel_futures=True)
    ready = all(r.status == "ok" for r in results if r.core)
    return Readiness(ready=ready, checks=tuple(results))


def database_check(engine: Engine) -> Check:
    def run() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    return Check("database", run)


def migrations_check(engine: Engine, settings: DatabaseSettings) -> Check:
    def run() -> None:
        if not migrations_at_head(engine, settings):
            raise CheckFailedError("database schema is not at the latest migration")

    return Check("migrations", run)


def blob_dir_check(directory: Path) -> Check:
    def run() -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".health-", delete=True) as probe:
            probe.write(b"ok")
            probe.flush()

    return Check("blob_store", run)


def gotenberg_check(base_url: str) -> Check:
    def run() -> None:
        response = httpx.get(f"{base_url}/health", timeout=CHECK_TIMEOUT_SECONDS)
        if response.status_code != httpx.codes.OK:
            raise CheckFailedError(f"gotenberg answered {response.status_code}")

    return Check("gotenberg", run)


def integration_results(settings: Settings) -> tuple[CheckResult, ...]:
    """Informational: whether each optional integration is configured."""
    flags = {
        "ai": settings.ai.configured,
        "email": settings.email.configured,
        "stripe": settings.stripe.configured,
    }
    return tuple(
        CheckResult(name, "configured" if ok else "not_configured", core=False, duration_ms=0)
        for name, ok in flags.items()
    )


def core_checks(settings: Settings, engine: Engine) -> list[Check]:
    return [
        database_check(engine),
        migrations_check(engine, settings.db),
        blob_dir_check(settings.blob_store.dir),
        gotenberg_check(settings.gotenberg.base_url),
    ]
