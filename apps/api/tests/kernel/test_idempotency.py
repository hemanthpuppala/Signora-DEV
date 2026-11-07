"""Idempotency tests (backbone LLD §3.7)."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Sequence
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import Engine, text

from signora.entrypoints.api import create_app
from signora.kernel.config import DatabaseSettings, Settings, load_settings
from signora.kernel.db import Database
from signora.kernel.errors import Conflict
from signora.kernel.health import Check
from signora.kernel.idempotency import IdempotencyGuard, idempotency_guard
from signora.kernel.idempotency import housekeeping as idem_housekeeping
from signora.kernel.jobs import JobContext, JobRegistry
from signora.kernel.jobs.core import claim, enqueue


class NewThing(BaseModel):
    name: str
    delay: float = 0.0
    fail: bool = False
    lock: int | None = None


def _side_effect(uow_db: Database, marker: str) -> int:
    with uow_db.unit_of_work() as uow:
        return int(
            uow.session.execute(
                text("SELECT count(*) FROM jobs WHERE kind = :k"), {"k": marker}
            ).scalar_one()
        )


def _router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/test/things/{bucket}", status_code=201)
    def create_thing(
        bucket: str,
        body: NewThing,
        request: Request,
        guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
    ) -> JSONResponse:
        database: Database = request.app.state.database
        with database.unit_of_work() as uow:
            if (replay := guard.begin(uow)) is not None:
                return replay
            time.sleep(body.delay)
            if body.lock is not None:  # waits on a lock held elsewhere (not the key lock)
                uow.session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": body.lock})
            uow.session.execute(
                text("INSERT INTO jobs (kind) VALUES (:k)"), {"k": f"thing:{bucket}:{body.name}"}
            )
            if body.fail:
                raise Conflict("refused")
            return guard.finish(uow, 201, {"bucket": bucket, "name": body.name})

    @router.post("/api/v1/test/uploads", status_code=201)
    def upload(
        request: Request,
        title: Annotated[str, Form()],
        document: Annotated[UploadFile, File()],
        guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
    ) -> JSONResponse:
        database: Database = request.app.state.database
        size = len(document.file.read())
        with database.unit_of_work() as uow:
            if (replay := guard.begin(uow)) is not None:
                return replay
            uow.session.execute(text("INSERT INTO jobs (kind) VALUES (:k)"), {"k": f"up:{title}"})
            return guard.finish(uow, 201, {"title": title, "size": size})

    return router


def _no_checks(_: Settings, __: Engine) -> Sequence[Check]:
    return []


@pytest.fixture
def client(test_db_settings: DatabaseSettings, engine: Engine) -> TestClient:
    settings = load_settings().model_copy(update={"db": test_db_settings})
    app = create_app(settings, engine=engine, checks_factory=_no_checks)
    app.include_router(_router())
    return TestClient(app, raise_server_exceptions=False)


def _post(client: TestClient, path: str, body: dict[str, Any], key: str | None) -> Any:
    headers = {"Idempotency-Key": key} if key is not None else {}
    return client.post(path, json=body, headers=headers)


def test_missing_key_is_rejected(client: TestClient) -> None:
    response = _post(client, "/api/v1/test/things/a", {"name": "x"}, key=None)

    assert response.status_code == 400
    assert response.json()["code"] == "idempotency-key-missing"


@pytest.mark.parametrize("key", ["", "x" * 256, "tab\tinside"])
def test_malformed_key_is_rejected(client: TestClient, key: str) -> None:
    response = _post(client, "/api/v1/test/things/a", {"name": "x"}, key=key)

    assert response.status_code == 400
    assert response.json()["code"] == "idempotency-key-invalid"


def test_repeat_returns_the_stored_response_and_runs_once(
    client: TestClient, committing_db: Database
) -> None:
    name, key = f"n-{uuid.uuid4()}", str(uuid.uuid4())

    first = _post(client, "/api/v1/test/things/a", {"name": name}, key)
    second = _post(client, "/api/v1/test/things/a", {"name": name}, key)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json() == {"bucket": "a", "name": name}
    assert _side_effect(committing_db, f"thing:a:{name}") == 1


def test_same_key_with_a_different_body_is_rejected(client: TestClient) -> None:
    key = str(uuid.uuid4())
    _post(client, "/api/v1/test/things/a", {"name": "one"}, key)

    response = _post(client, "/api/v1/test/things/a", {"name": "two"}, key)

    assert response.status_code == 422
    assert response.json()["code"] == "idempotency-key-reused"


def test_key_order_in_json_does_not_change_the_fingerprint(client: TestClient) -> None:
    key, name = str(uuid.uuid4()), f"n-{uuid.uuid4()}"
    first = client.post(
        "/api/v1/test/things/a",
        content=f'{{"name": "{name}", "delay": 0}}',
        headers={"Idempotency-Key": key, "content-type": "application/json"},
    )
    second = client.post(
        "/api/v1/test/things/a",
        content=f'{{"delay":0,"name":"{name}"}}',
        headers={"Idempotency-Key": key, "content-type": "application/json"},
    )
    assert first.status_code == second.status_code == 201


def test_same_key_on_different_paths_is_two_actions(
    client: TestClient, committing_db: Database
) -> None:
    key, name = str(uuid.uuid4()), f"n-{uuid.uuid4()}"

    a = _post(client, "/api/v1/test/things/project-a", {"name": name}, key)
    b = _post(client, "/api/v1/test/things/project-b", {"name": name}, key)

    assert a.json()["bucket"] == "project-a"
    assert b.json()["bucket"] == "project-b"
    assert _side_effect(committing_db, f"thing:project-b:{name}") == 1


def test_failed_first_request_is_not_stored_and_retry_runs(
    client: TestClient, committing_db: Database
) -> None:
    key, name = str(uuid.uuid4()), f"n-{uuid.uuid4()}"

    failed = _post(client, "/api/v1/test/things/a", {"name": name, "fail": True}, key)
    retried = _post(client, "/api/v1/test/things/a", {"name": name, "fail": True}, key)

    assert failed.status_code == retried.status_code == 409
    assert retried.json()["code"] == "conflict"  # ran again, not a replay or a key error
    assert _side_effect(committing_db, f"thing:a:{name}") == 0


def _concurrent(client: TestClient, body: dict[str, Any], key: str, stagger: float) -> list[Any]:
    responses: list[Any] = []
    lock = threading.Lock()

    def call() -> None:
        response = _post(client, "/api/v1/test/things/a", body, key)
        with lock:
            responses.append(response)

    first = threading.Thread(target=call)
    first.start()
    time.sleep(stagger)
    second = threading.Thread(target=call)
    second.start()
    first.join()
    second.join()
    return responses


def test_concurrent_duplicate_waits_and_gets_the_stored_response(
    client: TestClient, committing_db: Database
) -> None:
    name = f"n-{uuid.uuid4()}"
    responses = _concurrent(client, {"name": name, "delay": 0.8}, str(uuid.uuid4()), stagger=0.2)

    assert sorted(r.status_code for r in responses) == [201, 201]
    assert _side_effect(committing_db, f"thing:a:{name}") == 1


def test_concurrent_duplicate_gets_409_when_the_first_takes_too_long(
    client: TestClient, committing_db: Database
) -> None:
    name = f"n-{uuid.uuid4()}"
    responses = _concurrent(client, {"name": name, "delay": 3.0}, str(uuid.uuid4()), stagger=0.2)

    by_status = {r.status_code: r for r in responses}
    assert set(by_status) == {201, 409}
    assert by_status[409].headers["Retry-After"] == "1"
    assert by_status[409].json()["code"] == "request-in-progress"
    assert _side_effect(committing_db, f"thing:a:{name}") == 1


def test_later_lock_waits_are_not_capped_by_the_key_timeout(
    client: TestClient, committing_db: Database
) -> None:
    """LLD §3.4: after the key insert, waiting > 2 s on another lock still succeeds."""
    lock_id, name = 7_000_000 + int(uuid.uuid4().int % 1_000_000), f"n-{uuid.uuid4()}"
    held, release = threading.Event(), threading.Event()

    def hold_lock() -> None:
        with committing_db.unit_of_work() as uow:
            uow.session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_id})
            held.set()
            release.wait(timeout=10)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert held.wait(timeout=5)
    threading.Timer(3.0, release.set).start()

    response = _post(
        client, "/api/v1/test/things/a", {"name": name, "lock": lock_id}, str(uuid.uuid4())
    )
    holder.join()

    assert response.status_code == 201


def test_multipart_retry_with_a_new_boundary_is_replayed(
    client: TestClient, committing_db: Database
) -> None:
    key, title = str(uuid.uuid4()), f"t-{uuid.uuid4()}"
    content = b"%PDF-1.7 test document bytes"

    responses = [
        client.post(
            "/api/v1/test/uploads",
            data={"title": title},
            files={"document": ("agreement.pdf", content, "application/pdf")},
            headers={"Idempotency-Key": key},
        )
        for _ in range(2)
    ]

    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json() == responses[1].json() == {"title": title, "size": len(content)}
    assert _side_effect(committing_db, f"up:{title}") == 1


def test_multipart_with_different_file_content_is_rejected(client: TestClient) -> None:
    key = str(uuid.uuid4())
    for content, expected in ((b"first", 201), (b"second", 422)):
        response = client.post(
            "/api/v1/test/uploads",
            data={"title": "same"},
            files={"document": ("a.pdf", content, "application/pdf")},
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == expected


def test_retention_sweep_removes_keys_older_than_24_hours(committing_db: Database) -> None:
    scope = f"test:{uuid.uuid4()}"
    with committing_db.unit_of_work() as uow:
        for key, hours in (("old", 25), ("new", 1)):
            uow.session.execute(
                text(
                    "INSERT INTO idempotency_keys (scope, key, request_hash, created_at)"
                    " VALUES (:s, :k, :h, now() - make_interval(hours => :hours))"
                ),
                {"s": scope, "k": key, "h": bytes(32), "hours": hours},
            )
    reg = JobRegistry()
    idem_housekeeping.register(reg)
    with committing_db.unit_of_work() as uow:
        enqueue(uow.session, idem_housekeeping.SWEEP, dedupe_key=scope, jobs_registry=reg)
    with committing_db.unit_of_work() as uow:
        (job,) = claim(uow.session, reg, 1)

    idem_housekeeping.purge_expired_keys(
        JobContext(job.id, job.kind, job.payload, job.meta, job.attempt, committing_db)
    )

    with committing_db.unit_of_work() as uow:
        remaining = set(
            uow.session.execute(
                text("SELECT key FROM idempotency_keys WHERE scope = :s"), {"s": scope}
            ).scalars()
        )
    assert remaining == {"new"}
