"""Running detection for a version (Phase 5 LLD §1.2-1.4, §1.7): Postgres and a scripted AI."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.handlers import register_all
from signora.kernel.blobstore import LocalBlobStore
from signora.kernel.config import DatabaseSettings, Settings
from signora.kernel.db import Database
from signora.kernel.events import EventBus, bus
from signora.kernel.jobs import JobRegistry, registry
from signora.modules.detection import jobs as detection_jobs
from signora.modules.detection import run as detection_run
from signora.modules.detection.ai import AiError
from signora.modules.detection.jobs import RUN, SUBSCRIBER
from signora.modules.detection.run import restart_run, settle_dead_run
from signora.modules.documents import DocumentVersionProcessed, version_for_detection
from tests.modules.documents.conftest import create_department, csrf_headers, new_document
from tests.support import forms
from tests.support.ai import FakeAssigner, Fields, plain_answer
from tests.support.workers import running_worker, wait_until

DOCUMENTS = "/api/v1/documents"


def _processed(owner: TestClient, run: Callable[..., None], data: bytes) -> tuple[str, str]:
    department = create_department(owner)
    document = new_document(owner, department["id"], data).json()
    version_id = document["versions"][0]["id"]
    run(version_id)
    return document["id"], version_id


def _version(api: TestClient, document_id: str) -> Any:
    return api.get(f"{DOCUMENTS}/{document_id}").json()["versions"][0]


def _run_row(db: Database, version_id: str) -> Any:
    with db.unit_of_work() as uow:
        return uow.session.execute(
            text("SELECT * FROM detection_runs WHERE version_id = :v"), {"v": version_id}
        ).one_or_none()


def _count(db: Database, table: str, version_id: str) -> int:
    with db.unit_of_work() as uow:
        return int(
            uow.session.execute(
                text(f"SELECT count(*) FROM {table} WHERE version_id = :v"),  # noqa: S608 - our tables
                {"v": version_id},
            ).scalar_one()
        )


def test_detection_makes_the_version_ready_with_its_fields(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _processed(owner, run, forms.nda_like())
    assert _version(owner, document_id)["status"] == "detecting"
    ai = FakeAssigner()

    detect(version_id, ai)

    version = _version(owner, document_id)
    # 7 asked: the scripted AI gives both signatures to its one role, so they are one shared value.
    assert (version["status"], version["field_count"]) == ("ready", 6)
    after = owner.get(f"{DOCUMENTS}/{document_id}").json()
    assert after["current_version"]["number"] == 1
    assert after["name"] == "Client engagement letter"  # the upload's name, so the AI may rename
    assert after["description"].startswith("An engagement letter")
    row = _run_row(committing_db, version_id)
    assert (row.stage, row.fields_from, row.model) == ("done", "form_fields", "fake-model")
    assert _count(committing_db, "version_fields", version_id) == 6
    assert _count(committing_db, "version_roles", version_id) == 1
    assert (
        _count(committing_db, "field_placements", version_id) == 8
    )  # the radio's two, the signature's two
    with committing_db.unit_of_work() as uow:
        audited = uow.session.execute(
            text(
                "SELECT data FROM audit_events WHERE action = 'document.fields_detected' "
                "AND subject_id = :d"
            ),
            {"d": document_id},
        ).scalar_one()
    assert (audited["fields"], audited["calls"], audited["model"]) == (6, 1, "fake-model")
    assert "Governing Law" not in str(audited)  # no document text in the audit


def test_problems_go_back_once_and_the_second_answer_is_kept(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _processed(owner, run, forms.nda_like())

    def missing_one(fields: Fields) -> dict[str, Any]:
        answer = plain_answer(fields)
        answer["fields"].pop()
        return answer

    ai = FakeAssigner(missing_one)
    detect(version_id, ai)

    assert len(ai.messages) == 2
    assert "Your answer has these problems" in ai.messages[1][-1]["content"]
    row = _run_row(committing_db, version_id)
    assert [len(call["problems"]) for call in row.calls] == [1, 0]
    assert row.result["flags"]["repaired"] is True
    assert _version(owner, document_id)["status"] == "ready"


def test_a_passing_ai_failure_resumes_at_the_ai_stage_without_reading_again(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id, version_id = _processed(owner, run, forms.nda_like())
    with pytest.raises(AiError):  # the job retries it with backoff
        detect(version_id, FakeAssigner(AiError("ai_unavailable", "RateLimitError")))
    assert (_run_row(committing_db, version_id).stage, _version(owner, document_id)["status"]) == (
        "ai",
        "detecting",
    )

    def read_again(data: bytes) -> None:
        raise AssertionError("the document was read again")

    monkeypatch.setattr(detection_run, "read_document", read_again)
    detect(version_id, FakeAssigner())
    assert _version(owner, document_id)["status"] == "ready"


def test_no_ai_key_fails_the_version_now_and_try_again_resumes(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _processed(owner, run, forms.nda_like())
    detect(version_id, FakeAssigner(AiError("ai_not_configured", "AI_API_KEY is not set")))

    version = _version(owner, document_id)
    assert version["status"] == "failed"
    assert version["problem"] == {
        "code": "ai_not_configured",
        "message": "Field detection isn't set up yet",
        "can_retry": True,
    }
    retried = owner.post(
        f"{DOCUMENTS}/{document_id}/versions/{version_id}/retry", headers=csrf_headers(owner)
    )
    assert retried.status_code == 200, retried.text
    with committing_db.unit_of_work() as uow:  # Try again republished the event for detection
        queued = uow.session.execute(
            text(
                "SELECT count(*) FROM jobs WHERE kind = :k AND status = 'queued' "
                "AND payload->>'version_id' = :v"
            ),
            {"k": EventBus.job_kind(DocumentVersionProcessed.name, SUBSCRIBER), "v": version_id},
        ).scalar_one()
    assert queued >= 1
    detect(version_id, FakeAssigner())
    assert _version(owner, document_id)["status"] == "ready"


def test_a_replaced_run_writes_nothing(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _processed(owner, run, forms.nda_like())

    def replaced_meanwhile(fields: Fields) -> dict[str, Any]:
        with committing_db.unit_of_work() as uow:  # a person runs it again while this call runs
            version = version_for_detection(uow.session, uuid.UUID(version_id))
            assert version is not None
            restart_run(uow.session, version, requested_by=None)
        return plain_answer(fields)

    detect(version_id, FakeAssigner(replaced_meanwhile))

    row = _run_row(committing_db, version_id)
    assert (row.stage, row.answer) == ("read", None)  # the new run, untouched by the old job
    assert _version(owner, document_id)["status"] == "detecting"
    assert _count(committing_db, "version_fields", version_id) == 0


def test_a_dead_job_fails_the_version_with_its_stages_code(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _processed(owner, run, forms.nda_like())
    with pytest.raises(AiError):
        detect(version_id, FakeAssigner(AiError("ai_unavailable", "APIConnectionError")))
    with committing_db.unit_of_work() as uow:
        settle_dead_run(uow, {"version_id": version_id})
    problem = _version(owner, document_id)["problem"]
    assert (problem["code"], problem["can_retry"]) == ("ai_unavailable", True)


def test_nothing_to_fill_is_ready_with_no_fields_and_no_ai_call(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    empty = pymupdf.open()
    empty.new_page().insert_text((72, 72), "A letter with nothing to fill in.")
    document_id, version_id = _processed(owner, run, empty.tobytes())
    ai = FakeAssigner()

    detect(version_id, ai)

    assert ai.messages == []
    version = _version(owner, document_id)
    assert (version["status"], version["field_count"]) == ("ready", 0)
    assert _run_row(committing_db, version_id).result["flags"]["no_fields"] is True


def test_detection_is_wired_to_processing_and_to_runs_by_hand() -> None:
    register_all(registry)
    kind = registry.get(EventBus.job_kind(DocumentVersionProcessed.name, SUBSCRIBER))
    assert SUBSCRIBER in bus.subscribers(DocumentVersionProcessed)
    assert kind.on_dead is settle_dead_run
    fresh = JobRegistry()
    register_all(fresh)
    assert fresh.get(RUN).on_dead is settle_dead_run


def test_a_worker_runs_detection_after_processing_through_the_event(
    owner: TestClient,
    run: Callable[..., None],
    committing_db: Database,
    test_db_settings: DatabaseSettings,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalBlobStore(settings.blob_store.dir)
    monkeypatch.setattr(detection_jobs, "_dependencies", lambda: (store, FakeAssigner()))
    document_id, _ = _processed(owner, run, forms.nda_like())  # publishes DocumentVersionProcessed
    register_all(registry)
    with running_worker(committing_db, test_db_settings, registry):
        wait_until(lambda: _version(owner, document_id)["status"] == "ready", timeout=20)
    assert _version(owner, document_id)["field_count"] == 6
