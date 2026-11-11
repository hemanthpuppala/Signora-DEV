"""The review's findings on the bulk send, each as the case that showed it (PR 21)."""

from __future__ import annotations

import io
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from signora.kernel.db import Database
from signora.modules.envelopes import bulk, service
from signora.modules.envelopes.bulk_files import ROWS_SHEET, read_file, write_rows, write_template
from signora.modules.envelopes.bulk_sheet import (
    Column,
    RowIn,
    check_rows,
    columns_of,
    known_columns,
    match_headers,
)
from signora.modules.envelopes.form import Colleague
from signora.modules.identity_access import normalize_email
from tests.modules.envelopes.conftest import sendable
from tests.modules.envelopes.test_bulk import (
    clients,
    defaults,
    filled,
    rows_of,
    run_batch,
    send_batch,
)
from tests.modules.envelopes.test_bulk_sheet import EMAIL, cells, field, form
from tests.modules.envelopes.test_bulk_sheet import defaults as sheet_defaults
from tests.modules.identity_access.conftest import Account


def test_an_unexpected_error_on_one_row_does_not_sink_the_rows_after_it(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 5: a row whose send raises something that is not a refusal (a bug its data
    trips) is marked and the rest go on, on the first attempt."""
    doc = sendable(owner, run, detect)
    batch = send_batch(owner, doc, filled(owner, doc, clients(3)), defaults(doc, company)).json()
    real_send = service.send

    def break_on_the_second(*args: Any, **kwargs: Any) -> Any:
        if kwargs["request"].signers[0].name == "Client 1":
            raise RuntimeError("a bug this row's data trips")
        return real_send(*args, **kwargs)

    monkeypatch.setattr(service, "send", break_on_the_second)
    run_batch(committing_db, batch["id"])

    rows = rows_of(committing_db, batch["id"])
    assert [row.status for row in rows] == ["sent", "failed", "sent"]
    assert rows[1].error == bulk.GAVE_UP and rows[1].request is None
    done = owner.get(f"/api/v1/envelope-batches/{batch['id']}").json()
    assert (done["status"], done["sent"], done["failed"]) == ("finished", 2, 1)


def test_the_spreadsheets_lists_and_dates_refuse_other_values() -> None:
    """Finding 6: a rule that only hints lets anything be typed; each must stop it."""
    columns = [
        Column(key="a", header="Urgent", kind="checkbox", required=False),
        Column(key="b", header="Start", kind="date", required=False),
    ]
    book = load_workbook(io.BytesIO(write_template(columns, version_id=uuid.uuid4(), title="T")))
    rules = book[ROWS_SHEET].data_validations.dataValidation
    assert len(rules) == 2
    assert all(rule.showErrorMessage and rule.errorStyle in (None, "stop") for rule in rules)


def test_headers_that_differ_only_by_a_star_or_spaces_stay_apart() -> None:
    """Finding 7: columns are found by header without its star, case or extra spaces, so they
    must be unique by the same reading, and apart from the optional settings' headers."""
    sheet_form = form(countersigner=False)
    sheet_form.fields.extend(
        [
            field(uuid.uuid4(), "Notes", "text"),
            field(uuid.uuid4(), "Notes*", "text"),
            field(uuid.uuid4(), "notes  ", "text"),
            field(uuid.uuid4(), "Email code", "text"),
        ]
    )
    known = known_columns(sheet_form)
    matched = match_headers([column.header for column in known], known)
    assert matched.problems == []
    assert sorted(key for key in matched.keys if key) == sorted(column.key for column in known)


def test_a_protected_value_reads_back_from_xlsx_as_it_does_from_csv() -> None:
    """Finding 8: rows downloaded as CSV and saved again as XLSX keep the apostrophe that kept
    them from running as formulas; it is not part of the value in either format."""
    columns = [Column(key="p", header="Phone", kind="text", required=False)]
    protected = write_rows(columns, [["+1 555 0100"], ["plain"]]).decode("utf-8-sig").splitlines()
    assert protected[1] == "'+1 555 0100"
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = ROWS_SHEET
    sheet.append(["Phone"])
    sheet.append([protected[1]])
    sheet.append(["plain"])
    out = io.BytesIO()
    book.save(out)

    read = read_file("left-out.xlsx", out.getvalue())

    assert [cells[0] for _, cells in read.rows] == ["+1 555 0100", "plain"]


def test_cost_stays_linear_at_the_limits() -> None:
    """Finding 9: a thousand rows that all send to one address, a company of a thousand people,
    and a template of five hundred fields that share labels."""
    sheet_form = form()
    sheet_form.colleagues.extend(
        Colleague(user_id=uuid.uuid4(), name=f"Person {n}", email=f"p{n}@firm.example")
        for n in range(1000)
    )
    rows = [RowIn(row_no=n + 2, cells=cells()) for n in range(1000)]  # one address, 1,000 times
    started = time.perf_counter()
    checked = check_rows(
        sheet_form,
        columns_of(sheet_form),
        rows,
        sheet_defaults(sheet_form),
        normalize_email=normalize_email,
    )
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, elapsed
    said = [p.message for p in checked.sheet.rows[0].problems if p.key == EMAIL]
    assert said == ["Also in rows 3, 4, 5 and 996 more"]

    wide = form(countersigner=False)
    wide.fields.extend(field(uuid.uuid4(), "Notes", "text") for _ in range(500))
    started = time.perf_counter()
    headers = [column.header for column in columns_of(wide)]
    assert time.perf_counter() - started < 0.2
    assert len(set(headers)) == len(headers)


def test_a_name_or_email_is_one_line_in_a_single_send_too() -> None:
    """The review's note: what a spreadsheet's cells are cleaned of, the send dialog's names and
    emails are cleaned of as well, by the same definition."""
    from signora.modules.envelopes.sending import CopyIn, SignerIn

    signer = SignerIn(
        party_id=uuid.uuid4(),
        name="Maya\x00 Chen\r\nBcc: x@evil.example",
        email="maya@example.com\n",
    )
    assert signer.name == "Maya  Chen  Bcc: x@evil.example"
    assert signer.email == "maya@example.com "
    assert CopyIn(name="Records\tDesk", email="r@example.com").name == "Records Desk"


def test_a_row_takes_the_departments_countersigner_or_is_asked_for_one_in_the_table(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> None:
    """Finding 1: who countersigns is a cell of the row. With no usual countersigner in the
    department the cell is empty and flagged where rows are corrected; with one, it is filled in."""
    from tests.modules.envelopes.conftest import make_countersigner
    from tests.modules.envelopes.test_bulk import csv_of, upload

    doc = sendable(owner, run, detect)
    file = csv_of(["Client name", "Client email"], [["Maya Chen", "maya@example.com"]])

    without = upload(owner, doc, "clients.csv", file).json()
    firm = next(c for c in without["columns"] if c["header"] == "Firm countersigner")
    assert firm["required"] and [o["value"] for o in firm["options"]] == [company.email]
    assert without["rows"][0]["cells"].get(firm["key"], "") == ""
    assert {"key": firm["key"], "message": "Choose who countersigns as Firm", "level": "error"} in (
        without["rows"][0]["problems"]
    )

    make_countersigner(owner, doc.department_id, [str(company.user_id)])
    with_usual = upload(owner, doc, "clients.csv", file).json()
    assert with_usual["rows"][0]["cells"][firm["key"]] == company.email
    assert all(p["key"] != firm["key"] for p in with_usual["rows"][0]["problems"])
