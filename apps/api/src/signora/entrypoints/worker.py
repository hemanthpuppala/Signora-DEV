"""Worker process entry point (``signora worker``)."""

from __future__ import annotations

import signal
from pathlib import Path
from types import FrameType

from signora.handlers import register_all
from signora.kernel.config import get_settings
from signora.kernel.db import Database, create_db_engine
from signora.kernel.jobs import Worker, registry
from signora.kernel.logging import configure_logging, get_logger
from signora.kernel.migrations import migrations_at_head

# Touched every 10 s; the container healthcheck fails when it is older than 30 s (LLD §7.4).
HEARTBEAT_FILE = Path("/tmp/signora-worker.heartbeat")  # noqa: S108 - container-local file
# Pool users besides the job slots, each holding at most one connection at a time: the main loop
# (reclaim and claim), the lease renewer and the scheduler. LISTEN uses its own connection outside
# the pool (LLD §6.3a).
NON_JOB_POOL_USERS = 3


def worker_pool_size(concurrency: int) -> int:
    """One connection per job slot plus one per other pool user, so none ever waits for another."""
    return concurrency + NON_JOB_POOL_USERS


def run_worker() -> int:
    settings = get_settings()
    configure_logging(settings.app)
    log = get_logger("signora.worker")

    engine = create_db_engine(settings.db, pool_size=worker_pool_size(settings.worker.concurrency))
    if not migrations_at_head(engine, settings.db):
        log.error("worker.migrations_not_at_head", hint="run `signora migrate` first")
        engine.dispose()
        return 1

    recurring = register_all(registry)
    worker = Worker(
        database=Database(engine),
        conninfo=settings.db.conninfo,
        jobs_registry=registry,
        concurrency=settings.worker.concurrency,
        recurring=recurring,
        heartbeat_file=HEARTBEAT_FILE,
    )

    def _shutdown(signum: int, _: FrameType | None) -> None:
        log.info("worker.stopping", signal=signal.Signals(signum).name)
        worker.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        worker.run()
    finally:
        engine.dispose()
    return 0
