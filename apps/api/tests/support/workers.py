"""Helpers for tests that run real workers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from signora.kernel.config import DatabaseSettings
from signora.kernel.db import Database
from signora.kernel.jobs import JobRegistry, Worker


def wait_until(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


@contextmanager
def running_worker(
    database: Database, settings: DatabaseSettings, reg: JobRegistry, **options: Any
) -> Iterator[Worker]:
    worker = Worker(
        database=database,
        conninfo=settings.conninfo,
        jobs_registry=reg,
        concurrency=options.pop("concurrency", 4),
        poll_interval=options.pop("poll_interval", 0.2),
        **options,
    )
    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()
    try:
        yield worker
    finally:
        worker.stop()
        thread.join(timeout=20)
        assert not thread.is_alive(), "worker did not stop"
