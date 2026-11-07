"""Readiness check tests (backbone LLD §7.3)."""

from __future__ import annotations

import threading

from sqlalchemy import Engine

from signora.kernel.config import Settings as AppConfig
from signora.kernel.config import load_settings
from signora.kernel.health import Check, CheckFailedError, core_checks, run_checks


def _ok() -> None:
    return None


def _fail() -> None:
    raise CheckFailedError("component down")


def test_all_core_checks_ok_means_ready() -> None:
    readiness = run_checks([Check("a", _ok), Check("b", _ok)])

    assert readiness.ready
    assert [r.status for r in readiness.checks] == ["ok", "ok"]


def test_failed_core_check_means_not_ready_with_reason() -> None:
    readiness = run_checks([Check("a", _ok), Check("db", _fail)])

    assert not readiness.ready
    failed = next(r for r in readiness.checks if r.name == "db")
    assert failed.status == "failed"
    assert failed.message == "component down"


def test_failed_non_core_check_does_not_block_readiness() -> None:
    assert run_checks([Check("a", _ok), Check("optional", _fail, core=False)]).ready


def test_slow_check_times_out() -> None:
    release = threading.Event()

    def slow() -> None:
        release.wait(timeout=5)

    try:
        readiness = run_checks([Check("slow", slow)], timeout=0.2)
    finally:
        release.set()

    assert not readiness.ready
    assert readiness.checks[0].message is not None
    assert "timed out" in readiness.checks[0].message


def test_unexpected_exception_is_reported_by_type_only() -> None:
    def broken() -> None:
        raise RuntimeError("secret detail that must not leak")

    result = run_checks([Check("x", broken)]).checks[0]

    assert result.status == "failed"
    assert result.message == "RuntimeError"


def test_real_core_checks_pass_against_running_services(engine: Engine) -> None:
    """Integration: test database, migrations, blob dir and Gotenberg (needs `make up`)."""
    settings: AppConfig = load_settings()
    test_settings = settings.model_copy(
        update={"db": settings.db.model_copy(update={"name": "signora_test"})}
    )

    readiness = run_checks(core_checks(test_settings, engine))

    assert readiness.ready, readiness.checks
    assert {r.name for r in readiness.checks} == {
        "database",
        "migrations",
        "blob_store",
        "gotenberg",
    }
