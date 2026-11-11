"""A bulk send through the API and its job (Bulk send LLD §4.4, §8, §10)."""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import text

from signora.kernel.db import Database
from signora.kernel.errors import Conflict
from signora.kernel.jobs import JobContext
from signora.modules.envelopes import bulk, service
from tests.modules.documents.conftest import csrf_headers, log_in
from tests.modules.envelopes.conftest import Sendable, make_countersigner, sendable
from tests.modules.identity_access.conftest import Account, idempotency_key
from tests.modules.review.test_save import DOCUMENTS

SAMPLE = {"date": "2026-12-01", "checkbox": "yes", "number": "1", "email": "x@example.com"}
SETTINGS = {"reminder_interval_hours": 48, "max_reminders": 3, "expiry_days": 30}


def version_url(doc: Sendable) -> str:
    return f"{DOCUMENTS}/{doc.document_id}/versions/{doc.version_id}"


def upload(api: TestClient, doc: Sendable, name: str, data: bytes) -> Any:
    return api.post(
        f"{version_url(doc)}/bulk-rows",
        params={"filename": name},
        content=data,
        headers={**csrf_headers(api), "Content-Type": "application/octet-stream"},
    )


def csv_of(headers: list[str], rows: list[list[str]]) -> bytes:
    return "\n".join(",".join(line) for line in [headers, *rows]).encode()


def clients(count: int) -> list[list[str]]:
    tag = uuid.uuid4().hex[:8]  # its own addresses: the test database keeps earlier tests' mail
    return [[f"Client {n}", f"client{n}-{tag}@example.com"] for n in range(count)]


def filled(api: TestClient, doc: Sendable, people: list[list[str]]) -> dict[str, Any]:
    """A sheet for these people with every required column given a valid value: read from a file
    that has only the signer's columns, then filled in as a sender would fill the table."""
    sheet = upload(api, doc, "clients.csv", csv_of(["Client name", "Client email"], people)).json()
    for row in sheet["rows"]:
        for column in sheet["columns"]:
            if column["required"] and not row["cells"].get(column["key"]):
                row["cells"][column["key"]] = (
                    column["options"][0]["value"]
                    if column["options"]
                    else SAMPLE.get(column["kind"], "Delaware")
                )
    return dict(sheet)


def defaults(doc: Sendable, colleague: Account) -> dict[str, Any]:
    """What is chosen once for the batch. Who countersigns is each row's own cell."""
    return {"settings": SETTINGS}


def check(api: TestClient, doc: Sendable, sheet: dict[str, Any], batch: dict[str, Any]) -> Any:
    body = {
        "columns": [column["key"] for column in sheet["columns"]],
        "rows": [{"row_no": r["row_no"], "cells": r["cells"]} for r in sheet["rows"]],
        "defaults": batch,
    }
    return api.post(f"{version_url(doc)}/bulk-rows/check", json=body, headers=csrf_headers(api))


def send_batch(
    api: TestClient,
    doc: Sendable,
    sheet: dict[str, Any],
    batch: dict[str, Any],
    key: dict[str, str] | None = None,
) -> Any:
    body = {
        "version_id": doc.version_id,
        "file_name": "clients.csv",
        "rows": [{"row_no": r["row_no"], "cells": r["cells"]} for r in sheet["rows"]],
        "defaults": batch,
    }
    return api.post(
        f"{DOCUMENTS}/{doc.document_id}/envelope-batches",
        json=body,
        headers={**csrf_headers(api), **(key or idempotency_key())},
    )


def run_batch(database: Database, batch_id: str, *, attempt: int = 1) -> None:
    """Run the batch's job as the worker would."""
    payload = {"batch_id": batch_id}
    with database.unit_of_work() as uow:
        job_id = uow.session.execute(
            text(
                "INSERT INTO jobs (kind, status, attempts, payload) "
                "VALUES (:k, 'running', :a, CAST(:p AS jsonb)) RETURNING id"
            ),
            {"k": bulk.SEND_BATCH, "a": attempt, "p": json.dumps(payload)},
        ).scalar_one()
    bulk.send_batch(JobContext(job_id, bulk.SEND_BATCH, payload, {}, attempt, database))


def rows_of(database: Database, batch_id: str) -> list[Any]:
    with database.unit_of_work() as uow:
        return list(
            uow.session.execute(
                text(
                    "SELECT row_no, status, envelope_id, error, request FROM envelope_batch_rows "
                    "WHERE batch_id = :b ORDER BY row_no"
                ),
                {"b": batch_id},
            )
        )


def test_the_spreadsheet_for_a_version_has_its_columns_and_is_empty(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    doc = sendable(owner, run, detect)

    response = owner.get(f"{version_url(doc)}/bulk-template")

    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    assert "bulk%20send.xlsx" in response.headers["content-disposition"]
    headers = [c.value for c in load_workbook(io.BytesIO(response.content))["Envelopes"][1]]
    assert headers[:3] == ["Client name *", "Client email *", "Firm countersigner *"]
    assert "Effective date *" in headers and "Internal note" in headers
    # What the signer's own name and email fill is never asked.
    assert "Client printed name" not in headers
    # The spreadsheet as downloaded has no rows to send.
    again = upload(owner, doc, "template.xlsx", response.content)
    assert (again.status_code, again.json()["code"]) == (422, "bulk-file-empty")


def test_a_file_is_read_its_problems_shown_and_cleared_by_fixing_the_cell(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> None:
    doc = sendable(owner, run, detect)
    make_countersigner(owner, doc.department_id, [str(company.user_id)])
    file = csv_of(
        ["Client name", "Client email", "Effective date"],
        [
            ["Maya Chen", "maya@", "soon"],
            ["", "", ""],
            ["Sam Roe", "sam@example.com", "2026-12-01"],
        ],
    )

    sheet = upload(owner, doc, "clients.csv", file).json()

    by_header = {column["header"]: column["key"] for column in sheet["columns"]}
    first, second = sheet["rows"]  # the empty line is not a row; the others keep their numbers
    assert (first["row_no"], second["row_no"]) == (2, 4)
    said = {problem["key"]: problem["message"] for problem in first["problems"]}
    assert said[by_header["Client email"]] == "Enter a valid email address"
    assert said[by_header["Effective date"]] == "Enter a date"

    first["cells"][by_header["Client email"]] = "maya@example.com"
    first["cells"][by_header["Effective date"]] = "2026-12-01"
    for row in sheet["rows"]:  # the template's other required columns, filled in the table
        for column in sheet["columns"]:
            if column["required"] and not row["cells"].get(column["key"]):
                row["cells"][column["key"]] = (
                    column["options"][0]["text"] if column["options"] else "Delaware"
                )
    checked = check(owner, doc, sheet, defaults(doc, company))
    assert checked.status_code == 200, checked.text
    assert [row["problems"] for row in checked.json()["rows"]] == [[], []]


def test_a_file_with_the_wrong_columns_or_for_another_version_is_refused(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    doc = sendable(owner, run, detect)

    wrong = upload(owner, doc, "x.csv", csv_of(["Client name", "Shoe size"], [["Maya", "9"]]))
    assert wrong.status_code == 200
    assert wrong.json()["rows"] == []
    assert wrong.json()["problems"] == [
        'This file has a column "Shoe size" that this template does not ask for'
    ]

    template = owner.get(f"{version_url(doc)}/bulk-template").content
    book = load_workbook(io.BytesIO(template))
    book["_signora"]["A1"] = str(uuid.uuid4())
    book["Envelopes"].append(["Maya Chen", "maya@example.com"])
    out = io.BytesIO()
    book.save(out)
    outdated = upload(owner, doc, "old.xlsx", out.getvalue())
    assert (outdated.status_code, outdated.json()["code"]) == (409, "bulk-file-outdated")

    garbage = upload(owner, doc, "clients.xlsx", b"not a spreadsheet")
    assert (garbage.status_code, garbage.json()["code"]) == (422, "bulk-file-unreadable")


def test_a_batch_sends_one_envelope_per_row_once(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(3))
    key = idempotency_key()

    created = send_batch(owner, doc, sheet, defaults(doc, company), key)

    assert created.status_code == 201, created.text
    batch = created.json()
    assert (batch["status"], batch["total"], batch["sent"], batch["failed"]) == ("sending", 3, 0, 0)
    # The same request again (a double click, a retry) is the same batch, not a second one.
    assert send_batch(owner, doc, sheet, defaults(doc, company), key).json()["id"] == batch["id"]

    run_batch(committing_db, batch["id"])

    done = owner.get(f"/api/v1/envelope-batches/{batch['id']}").json()
    assert (done["status"], done["sent"], done["failed"]) == ("finished", 3, 0)
    rows = rows_of(committing_db, batch["id"])
    assert [row.status for row in rows] == ["sent", "sent", "sent"]
    assert all(row.request is None for row in rows)  # what was typed is kept by the envelope only
    envelopes = [owner.get(f"/api/v1/envelopes/{row.envelope_id}").json() for row in rows]
    assert [e["recipients"][0]["name"] for e in envelopes] == ["Client 0", "Client 1", "Client 2"]
    assert all(e["status"] == "sent" and e["reminder_interval_hours"] == 48 for e in envelopes)
    assert all(e["recipients"][1]["email"] == company.email for e in envelopes)  # the row's

    # The job run again (a worker that restarted) sends nothing twice.
    run_batch(committing_db, batch["id"], attempt=2)
    assert [row.envelope_id for row in rows_of(committing_db, batch["id"])] == [
        row.envelope_id for row in rows
    ]
    listed = owner.get(f"/api/v1/departments/{doc.department_id}/envelope-batches").json()
    assert [b["id"] for b in listed["batches"]] == [batch["id"]]


def test_a_batch_with_a_problem_sends_nothing(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(2))
    email_key = next(c["key"] for c in sheet["columns"] if c["header"] == "Client email")
    sheet["rows"][1]["cells"][email_key] = "not-an-email"

    refused = send_batch(owner, doc, sheet, defaults(doc, company))

    assert (refused.status_code, refused.json()["code"]) == (422, "bulk-rows-need-fixing")
    with committing_db.unit_of_work() as uow:
        written = uow.session.execute(
            text("SELECT count(*) FROM envelope_batches WHERE document_id = :d"),
            {"d": doc.document_id},
        ).scalar_one()
    assert written == 0


def test_a_row_refused_at_send_time_is_marked_and_the_rest_go_on(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(3))
    batch = send_batch(owner, doc, sheet, defaults(doc, company)).json()
    real_send = service.send

    def refuse_the_second(*args: Any, **kwargs: Any) -> Any:
        if kwargs["request"].signers[0].name == "Client 1":
            raise Conflict("The template was archived")
        return real_send(*args, **kwargs)

    monkeypatch.setattr(service, "send", refuse_the_second)
    run_batch(committing_db, batch["id"])

    done = owner.get(f"/api/v1/envelope-batches/{batch['id']}").json()
    assert (done["status"], done["sent"], done["failed"]) == ("finished", 2, 1)
    assert [(f["row_no"], f["error"]) for f in done["failures"]] == [
        (3, "The template was archived")
    ]
    assert done["failures"][0]["label"].startswith("Client 1 · client1-")
    assert all(row.request is None for row in rows_of(committing_db, batch["id"]))


def test_a_sender_who_was_deactivated_sends_nothing(
    make_client: Callable[..., TestClient],
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    add_member: Callable[..., Account],
    committing_db: Database,
) -> None:
    doc = sendable(owner, run, detect)
    editor = add_member(company, "read_write")
    api = make_client()
    log_in(api, editor.email)
    sheet = filled(api, doc, clients(2))
    batch = send_batch(api, doc, sheet, defaults(doc, company)).json()
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :u"), {"u": editor.user_id}
        )

    run_batch(committing_db, batch["id"])

    done = owner.get(f"/api/v1/envelope-batches/{batch['id']}").json()
    assert (done["status"], done["sent"], done["failed"]) == ("finished", 0, 2)
    assert {f["error"] for f in done["failures"]} == {bulk.NO_ACCESS}


def test_only_someone_who_may_send_may_send_in_bulk(
    make_client: Callable[..., TestClient],
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    add_member: Callable[..., Account],
    make_workspace: Callable[..., Account],
) -> None:
    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(1))
    batch = send_batch(owner, doc, sheet, defaults(doc, company)).json()

    reader = make_client()
    log_in(reader, add_member(company, "read").email)
    assert reader.get(f"{version_url(doc)}/bulk-template").status_code in (403, 404)
    assert send_batch(reader, doc, sheet, defaults(doc, company)).status_code in (403, 404)
    assert reader.get(f"/api/v1/envelope-batches/{batch['id']}").status_code in (403, 404)

    stranger = make_client()
    log_in(stranger, make_workspace().email)
    assert stranger.get(f"/api/v1/envelope-batches/{batch['id']}").status_code == 404
    assert stranger.get(f"{version_url(doc)}/bulk-template").status_code == 404


def test_a_batch_whose_job_died_is_finished_with_its_unsent_rows_marked(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    doc = sendable(owner, run, detect)
    batch = send_batch(owner, doc, filled(owner, doc, clients(2)), defaults(doc, company)).json()

    with committing_db.unit_of_work() as uow:
        bulk.give_up(uow, {"batch_id": batch["id"]})

    done = owner.get(f"/api/v1/envelope-batches/{batch['id']}").json()
    assert (done["status"], done["sent"], done["failed"]) == ("finished", 0, 2)
    assert {f["error"] for f in done["failures"]} == {bulk.GAVE_UP}
    assert all(row.request is None for row in rows_of(committing_db, batch["id"]))


def test_rows_left_out_come_back_as_a_file(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> None:
    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(2))
    body = {
        "columns": [column["key"] for column in sheet["columns"]],
        "rows": [{"row_no": r["row_no"], "cells": r["cells"]} for r in sheet["rows"][:1]],
        "defaults": defaults(doc, company),
    }

    response = owner.post(
        f"{version_url(doc)}/bulk-rows/left-out", json=body, headers=csrf_headers(owner)
    )

    assert response.status_code == 200, response.text
    lines = response.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Client name *,Client email *")
    assert len(lines) == 2 and lines[1].startswith("Client 0,client0-")
