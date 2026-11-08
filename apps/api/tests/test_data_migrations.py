"""Data migrations that rewrite rows (each checked on a throwaway database)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text

from signora.kernel.config import DatabaseSettings
from signora.kernel.migrations import alembic_config

SYSTEM_WORKSPACE = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def scratch(test_db_settings: DatabaseSettings) -> Iterator[DatabaseSettings]:
    name = f"signora_data_{uuid.uuid4().hex[:8]}"
    admin = create_engine(
        test_db_settings.model_copy(update={"name": "postgres"}).url, isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield test_db_settings.model_copy(update={"name": name})
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _role(engine: Engine, key: str, permissions: list[str], description: str) -> uuid.UUID:
    with engine.begin() as connection:
        workspace = SYSTEM_WORKSPACE  # the only company a bare database has
        return uuid.UUID(
            str(
                connection.execute(
                    text(
                        "INSERT INTO roles (workspace_id, key, name, description, permissions, "
                        "is_system) VALUES (:w, :k, 'x', :d, CAST(:p AS text[]), true) RETURNING id"
                    ),
                    {"w": workspace, "k": key, "d": description, "p": permissions},
                ).scalar_one()
            )
        )


def _read(engine: Engine, role_id: uuid.UUID) -> tuple[list[str], str]:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT permissions, description FROM roles WHERE id = :id"), {"id": role_id}
        ).one()
    return list(row.permissions), row.description


def test_0012_renames_file_permissions_in_every_role_and_back(scratch: DatabaseSettings) -> None:
    config = alembic_config(scratch)
    command.upgrade(config, "0011")
    engine = create_engine(scratch.url)
    viewer_old = "Can see departments, files and signed agreements, but can't change anything."
    custom = _role(engine, "custom", ["members.directory", "files.send"], "Our own words")
    viewer = _role(engine, "read", [], viewer_old)
    editor = _role(engine, "read_write", ["files.view_sends", "files.send"], "x")

    command.upgrade(config, "0012")

    assert _read(engine, custom) == (["members.directory", "documents.send"], "Our own words")
    assert _read(engine, viewer)[1] == (
        "Can see departments, documents and signed agreements, but can't change anything."
    )
    assert _read(engine, editor)[0] == ["documents.view_sends", "documents.send"]

    command.downgrade(config, "0011")

    assert _read(engine, custom)[0] == ["members.directory", "files.send"]
    assert _read(engine, viewer)[1] == viewer_old
    engine.dispose()
