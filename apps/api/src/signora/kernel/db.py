"""Database access: engine, metadata conventions and the unit of work (backbone LLD §6.3a, §7.1a).

Synchronous SQLAlchemy 2 with psycopg 3 (ADR B-1). Every request or job step runs inside one
``UnitOfWork``: it commits when the block finishes and rolls back when an exception escapes. A
domain service that must persist an outcome *and* fail the request (e.g. a failed signing-code
attempt) calls ``uow.commit()`` explicitly before raising; nothing is left to roll back.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Self

from sqlalchemy import Connection, Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from signora.kernel.config import DatabaseSettings

# Deterministic constraint and index names, so migrations are reviewable and portable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base for every module's tables."""

    metadata = metadata


POOL_TIMEOUT_SECONDS = 5


def create_db_engine(
    settings: DatabaseSettings,
    *,
    pool_size: int,
    pool_timeout: float = POOL_TIMEOUT_SECONDS,
) -> Engine:
    """Engine with a fixed-size pool that fails fast when exhausted (no overflow connections)."""
    return create_engine(
        settings.url,
        pool_size=pool_size,
        max_overflow=0,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,
        connect_args={"application_name": "signora"},
    )


class UnitOfWork:
    """One database transaction. Use through ``Database.unit_of_work()``."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def commit(self) -> None:
        """Commit now. Later statements in the same block start a new transaction."""
        self.session.commit()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()


class Database:
    """Owns the session factory. Bound to an engine, or to a connection in tests."""

    def __init__(self, bind: Engine | Connection) -> None:
        # With a Connection bind (tests), each unit of work becomes a SAVEPOINT inside the test's
        # outer transaction, which the test rolls back afterwards.
        self._sessions = sessionmaker(
            bind=bind,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    @contextmanager
    def unit_of_work(self) -> Iterator[UnitOfWork]:
        with UnitOfWork(self._sessions()) as uow:
            yield uow
