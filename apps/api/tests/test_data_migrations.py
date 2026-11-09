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


def _processed_version(engine: Engine, *, status: str = "processed") -> uuid.UUID:
    """A department, a document and one version in the system company, as Phase 4 left them."""
    with engine.begin() as connection:
        run = connection.execute
        role = run(
            text("SELECT id FROM roles WHERE workspace_id = :w LIMIT 1"), {"w": SYSTEM_WORKSPACE}
        )
        role_id = role.scalar_one_or_none() or _role(engine, "owner", [], "x")
        user = run(
            text(
                "INSERT INTO users (workspace_id, role_id, email, name, password_hash) "
                "VALUES (:w, :r, :e, 'Rosa Hale', 'x') RETURNING id"
            ),
            {"w": SYSTEM_WORKSPACE, "r": role_id, "e": f"{uuid.uuid4().hex}@example.com"},
        ).scalar_one()
        department = run(
            text(
                "INSERT INTO departments (workspace_id, name, created_by) "
                "VALUES (:w, :n, :u) RETURNING id"
            ),
            {"w": SYSTEM_WORKSPACE, "n": f"Finance {uuid.uuid4().hex[:6]}", "u": user},
        ).scalar_one()
        document = run(
            text(
                "INSERT INTO documents (workspace_id, department_id, name, created_by) "
                "VALUES (:w, :d, 'NDA', :u) RETURNING id"
            ),
            {"w": SYSTEM_WORKSPACE, "d": department, "u": user},
        ).scalar_one()
        return uuid.UUID(
            str(
                run(
                    text(
                        "INSERT INTO document_versions (workspace_id, document_id, version_no, "
                        "status, source_sha256, source_kind, source_filename, source_bytes, "
                        "uploaded_by, pdf_sha256, pdf_bytes, page_count) VALUES (:w, :d, 1, :s, "
                        "'abc', 'pdf', 'NDA.pdf', 10, :u, 'def', 10, 1) RETURNING id"
                    ),
                    {"w": SYSTEM_WORKSPACE, "d": document, "u": user, "s": status},
                ).scalar_one()
            )
        )


def test_0016_queues_detection_for_every_processed_version_and_back(
    scratch: DatabaseSettings,
) -> None:
    from signora.modules.documents.processing import DocumentVersionProcessed

    config = alembic_config(scratch)
    command.upgrade(config, "0015")
    engine = create_engine(scratch.url)
    processed = _processed_version(engine)
    locked = _processed_version(engine, status="needs_password")

    command.upgrade(config, "0016")

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, status FROM document_versions")).all()
        statuses = {row.id: row.status for row in rows}
        jobs = connection.execute(
            text("SELECT kind, payload, dedupe_key FROM jobs WHERE kind LIKE 'event:%'")
        ).all()
    assert statuses == {processed: "detecting", locked: "needs_password"}
    (job,) = jobs
    assert job.kind == "event:DocumentVersionProcessed:detection"
    event = DocumentVersionProcessed.model_validate(job.payload)  # what the subscriber will read
    assert event.version_id == processed
    assert job.dedupe_key == f"event:{event.event_id}:detection"

    command.downgrade(config, "0015")

    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT status FROM document_versions WHERE id = :id"), {"id": processed}
            ).scalar_one()
            == "processed"
        )
        assert connection.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0
    engine.dispose()
