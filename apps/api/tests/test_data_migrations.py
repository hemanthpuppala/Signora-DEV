"""Data migrations that rewrite rows (each checked on a throwaway database)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

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


def test_0031_queues_detection_for_every_scanned_version_and_back(
    scratch: DatabaseSettings,
) -> None:
    """Phase 5c: a version stopped at needs_ocr becomes detecting with its detection queued; the
    downgrade puts it back and removes the job, leaving other versions and jobs alone."""
    from signora.modules.documents.processing import DocumentVersionProcessed

    config = alembic_config(scratch)
    command.upgrade(config, "0030")
    engine = create_engine(scratch.url)
    scanned = _processed_version(engine, status="needs_ocr")
    locked = _processed_version(engine, status="needs_password")

    command.upgrade(config, "0031")

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, status FROM document_versions")).all()
        jobs = connection.execute(
            text("SELECT payload FROM jobs WHERE dedupe_key LIKE '%scanned-0031'")
        ).all()
    assert {row.id: row.status for row in rows} == {scanned: "detecting", locked: "needs_password"}
    (job,) = jobs
    assert DocumentVersionProcessed.model_validate(job.payload).version_id == scanned

    command.downgrade(config, "0030")

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, status FROM document_versions")).all()
        left = connection.execute(
            text("SELECT count(*) FROM jobs WHERE dedupe_key LIKE '%scanned-0031'")
        ).scalar_one()
    assert {row.id: row.status for row in rows} == {scanned: "needs_ocr", locked: "needs_password"}
    assert left == 0
    engine.dispose()


def test_0018_keeps_ready_versions_in_review_without_a_current_one_and_back(
    scratch: DatabaseSettings,
) -> None:
    """Phase 6 §9.3: ready stays ready (in review), current means approved so none is current, each
    version with a run gets its review revision, and the names lose their ``ai_`` prefix."""
    config = alembic_config(scratch)
    command.upgrade(config, "0017")
    engine = create_engine(scratch.url)
    version = _processed_version(engine, status="ready")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE documents SET current_version_id = :v WHERE id = "
                "(SELECT document_id FROM document_versions WHERE id = :v)"
            ),
            {"v": version},
        )
        connection.execute(
            text("UPDATE document_versions SET ai_name = 'Mutual NDA' WHERE id = :v"),
            {"v": version},
        )
        connection.execute(
            text(
                "INSERT INTO detection_runs (version_id, run_id, workspace_id, stage, finished_at) "
                "VALUES (:v, gen_random_uuid(), :w, 'done', now())"
            ),
            {"v": version, "w": SYSTEM_WORKSPACE},
        )
        field = connection.execute(
            text(
                "INSERT INTO version_fields (workspace_id, version_id, key, label, holds, "
                "filled_by, required, sensitive, origin) VALUES (:w, :v, 'agreement.date', "
                "'Effective date', 'date', 'sender', true, false, 'detected') RETURNING id"
            ),
            {"v": version, "w": SYSTEM_WORKSPACE},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO field_placements (workspace_id, version_id, field_id, page, x0, y0, "
                "x1, y1, kind) VALUES (:w, :v, :f, 1, 10, 20, 110, 40, 'blank')"
            ),
            {"v": version, "w": SYSTEM_WORKSPACE, "f": field},
        )

    command.upgrade(config, "0018")

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT v.status, v.name, d.current_version_id, r.revision, r.baseline_version_id, "
                "r.proposal FROM document_versions v JOIN documents d ON d.id = v.document_id "
                "JOIN version_reviews r ON r.version_id = v.id WHERE v.id = :v"
            ),
            {"v": version},
        ).one()
    assert (row.status, row.name, row.current_version_id, row.revision) == (
        "ready",
        "Mutual NDA",
        None,
        0,
    )
    # Unedited, so its rows are the AI's proposal: the metrics' baseline (§1.5).
    assert row.baseline_version_id == version
    assert row.proposal == [
        {
            "page": 1,
            "rect": [10, 20, 110, 40],
            "holds": "date",
            "label": "Effective date",
            "filled_by": "sender",
            "party_id": None,
        }
    ]

    command.downgrade(config, "0017")

    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT ai_name FROM document_versions WHERE id = :v"), {"v": version}
            ).scalar_one()
            == "Mutual NDA"
        )
    engine.dispose()


def test_0019_moves_the_email_code_to_envelopes_which_keep_what_they_sent_and_back(
    scratch: DatabaseSettings,
) -> None:
    """Phase 7 §4, §9: the document's "Require email code" goes (a send's setting now); an
    envelope's version, settings and the sender's values cannot change once sent."""
    config = alembic_config(scratch)
    command.upgrade(config, "0018")
    engine = create_engine(scratch.url)
    version = _processed_version(engine, status="ready")

    command.upgrade(config, "0019")

    with engine.begin() as connection:
        columns = connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'documents'"
            )
        ).scalars()
        assert "require_email_code" not in set(columns)
        row = connection.execute(
            text(
                "SELECT v.workspace_id, v.document_id, d.department_id, d.created_by "
                "FROM document_versions v JOIN documents d ON d.id = v.document_id WHERE v.id = :v"
            ),
            {"v": version},
        ).one()
        envelope = connection.execute(
            text(
                "INSERT INTO envelopes (workspace_id, department_id, document_id, version_id, "
                "title, require_email_code, reminder_interval_hours, max_reminders, expires_at, "
                "notify_emails, sent_by) VALUES (:w, :dep, :doc, :v, 'NDA · Maya', true, 24, 5, "
                "now() + interval '14 days', '{}', :u) RETURNING id"
            ),
            {
                "w": row.workspace_id,
                "dep": row.department_id,
                "doc": row.document_id,
                "v": version,
                "u": row.created_by,
            },
        ).scalar_one()
    # Its expiry may be extended later (as DocuSign allows); what was sent may not change.
    for change in (
        "UPDATE envelopes SET require_email_code = false WHERE id = :e",
        "UPDATE envelopes SET max_reminders = 1 WHERE id = :e",
        "UPDATE envelopes SET notify_emails = '{a@example.com}' WHERE id = :e",
    ):
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(text(change), {"e": envelope})
    with engine.begin() as connection:  # a rename is allowed; the state moves on
        connection.execute(
            text("UPDATE envelopes SET title = 'Renamed', status = 'opened' WHERE id = :e"),
            {"e": envelope},
        )
        connection.execute(text("DELETE FROM envelopes WHERE id = :e"), {"e": envelope})

    command.downgrade(config, "0018")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT require_email_code FROM documents WHERE id = :d"), {"d": row.document_id}
        ).scalar_one()
    engine.dispose()


def test_0027_clears_the_flags_left_on_approved_versions_and_keeps_them_frozen(
    scratch: DatabaseSettings,
) -> None:
    """Approving accepted every flag left (Phase 6 §2.2): versions approved before approval cleared
    them lose theirs; one still in review keeps its; approved fields stay frozen after."""
    config = alembic_config(scratch)
    command.upgrade(config, "0026")
    engine = create_engine(scratch.url)

    def flagged_version() -> tuple[uuid.UUID, uuid.UUID]:
        version = _processed_version(engine, status="ready")
        with engine.begin() as connection:
            field = connection.execute(
                text(
                    "INSERT INTO version_fields (workspace_id, version_id, key, label, holds, "
                    "filled_by, required, sensitive, origin, needs_review) VALUES (:w, :v, "
                    "'agreement.date', 'Effective date', 'date', 'sender', true, false, "
                    "'detected', 'two answers') RETURNING id"
                ),
                {"v": version, "w": SYSTEM_WORKSPACE},
            ).scalar_one()
        return version, field

    approved, approved_field = flagged_version()
    _, in_review_field = flagged_version()
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE document_versions SET status = 'approved', approved_at = now(), "
                "approved_by = uploaded_by WHERE id = :v"
            ),
            {"v": approved},
        )

    command.upgrade(config, "0027")

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, needs_review FROM version_fields WHERE id IN (:a, :b)"),
            {"a": approved_field, "b": in_review_field},
        ).all()
    flags: dict[uuid.UUID, str | None] = {row.id: row.needs_review for row in rows}
    assert flags == {approved_field: None, in_review_field: "two answers"}
    with pytest.raises(IntegrityError), engine.begin() as connection:  # still frozen
        connection.execute(
            text("UPDATE version_fields SET label = 'Changed' WHERE id = :f"), {"f": approved_field}
        )
    engine.dispose()


def test_0032_keys_logos_by_registrable_domain_and_registers_each_for_a_look_up(
    scratch: DatabaseSettings,
) -> None:
    """Company logo LLD §6 (revised): websites become their registrable domain, each domain gets
    one shared row with a look-up due, and the per-workspace logo columns go."""
    config = alembic_config(scratch)
    command.upgrade(config, "0031")
    engine = create_engine(scratch.url)
    with engine.begin() as connection:  # the one workspace there is: give it a website
        connection.execute(
            text(
                "UPDATE workspaces SET website = 'app.scoutboard.com', logo_sha256 = 'x', "
                "logo_bytes = 1, logo_check_due_at = now() WHERE id = :s"
            ),
            {"s": SYSTEM_WORKSPACE},
        )

    command.upgrade(config, "0032")

    with engine.connect() as connection:
        websites = connection.execute(
            text("SELECT DISTINCT website FROM workspaces WHERE website IS NOT NULL")
        ).scalars()
        logos = connection.execute(
            text("SELECT domain, logo_sha256, check_due_at <= now() AS due FROM company_logos")
        ).all()
        columns = connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'workspaces' AND column_name LIKE 'logo%'"
            )
        ).scalars()
        assert list(websites) == ["scoutboard.com"]
        assert [(row.domain, row.logo_sha256, row.due) for row in logos] == [
            ("scoutboard.com", None, True)
        ]
        assert list(columns) == []

    command.downgrade(config, "0031")
    command.upgrade(config, "0032")
    engine.dispose()
