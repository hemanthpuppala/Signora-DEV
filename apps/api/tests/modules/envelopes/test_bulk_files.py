"""A bulk send's files (Bulk send LLD §4.1, §4.2): the spreadsheet made for a version read back,
and a filled XLSX or CSV as text."""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime

import pytest
from openpyxl import Workbook, load_workbook

from signora.modules.envelopes.bulk_files import (
    GUIDE_SHEET,
    ROWS_SHEET,
    read_file,
    write_rows,
    write_template,
)
from signora.modules.envelopes.bulk_sheet import MAX_ROWS, Column, match_headers
from signora.modules.envelopes.errors import EmptyFile, TooManyRows, UnreadableFile
from signora.modules.envelopes.form import Option

VERSION = uuid.uuid4()
COLUMNS = [
    Column(key="signer:c:name", header="Client name", kind="text", required=True),
    Column(key="signer:c:email", header="Client email", kind="email", required=True),
    Column(key="field:start", header="Start date", kind="date", required=False),
    Column(
        key="field:plan",
        header="Plan",
        kind="choice",
        required=False,
        options=[Option(value="gold", text="Gold"), Option(value="silver", text="Silver")],
    ),
    Column(key="field:urgent", header="Urgent", kind="checkbox", required=False),
    Column(key="field:zip", header="ZIP", kind="text", required=False),
]


def xlsx(rows: list[list[object]], sheet: str = ROWS_SHEET) -> bytes:
    book = Workbook()
    book.active.title = sheet  # type: ignore[union-attr]
    for row in rows:
        book.active.append(row)  # type: ignore[union-attr]
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_the_template_reads_back_as_its_own_columns() -> None:
    data = write_template(COLUMNS, version_id=VERSION, title="Engagement Letter")
    book = load_workbook(io.BytesIO(data))
    headers = [cell.value for cell in book[ROWS_SHEET][1]]
    assert headers == ["Client name *", "Client email *", "Start date", "Plan", "Urgent", "ZIP"]
    assert match_headers([str(h) for h in headers], COLUMNS).problems == []
    # Choices and ticks are lists in the cells; the guide says what each column takes.
    lists = {str(v.sqref): v.formula1 for v in book[ROWS_SHEET].data_validations.dataValidation}
    assert lists[f"D2:D{MAX_ROWS + 1}"] == '"Gold,Silver"'
    assert lists[f"E2:E{MAX_ROWS + 1}"] == '"yes,no"'
    guide = [[cell.value for cell in row] for row in book[GUIDE_SHEET].iter_rows()]
    assert ["Plan", "Optional", "One of: Gold, Silver"] in guide
    assert book["_signora"].sheet_state == "hidden"
    # A template nobody has filled is an empty file, not a batch of one.
    with pytest.raises(EmptyFile):
        read_file("template.xlsx", data)


def test_a_filled_xlsx_is_read_as_what_a_person_would_type() -> None:
    data = xlsx(
        [
            ["Client name *", "Client email *", "Start date", "Plan", "Urgent", "ZIP", None],
            # A spreadsheet's date cell has no zone, and the format cannot hold one.
            ["Avery Lin", "avery@example.com", datetime(2026, 12, 1), "Gold", True, 2134.0, None],  # noqa: DTZ001
            [None, None, None, None, None, None, None],
            ["  Sam Roe ", "sam@example.com", date(2027, 1, 15), None, "no", "02134", "stray"],
        ]
    )
    read = read_file("clients.xlsx", data)
    assert read.headers == [
        "Client name *",
        "Client email *",
        "Start date",
        "Plan",
        "Urgent",
        "ZIP",
    ]
    # The empty row is skipped and the others keep their numbers in the file.
    assert read.rows == [
        (2, ["Avery Lin", "avery@example.com", "2026-12-01", "Gold", "yes", "2134"]),
        (4, ["Sam Roe", "sam@example.com", "2027-01-15", "", "no", "02134"]),
    ]
    assert read.version_id is None


def test_the_version_a_spreadsheet_was_made_for_comes_back() -> None:
    data = write_template(COLUMNS, version_id=VERSION, title="Engagement Letter")
    book = load_workbook(io.BytesIO(data))
    book[ROWS_SHEET].append(["Avery Lin", "avery@example.com"])
    out = io.BytesIO()
    book.save(out)
    read = read_file("clients.xlsx", out.getvalue())
    assert read.version_id == VERSION
    assert read.rows == [(2, ["Avery Lin", "avery@example.com", "", "", "", ""])]


@pytest.mark.parametrize(
    "text",
    [
        'Client name,Client email\nAvery Lin,avery@example.com\n\n"Roe, Sam",sam@example.com\n',
        'Client name;Client email\nAvery Lin;avery@example.com\n\n"Roe, Sam";sam@example.com\n',
        "\ufeffClient name,Client email\r\nAvery Lin,avery@example.com\r\n,\r\n"
        '"Roe, Sam",sam@example.com\r\n',
    ],
)
def test_a_csv_is_read_whatever_its_separator_or_byte_order_mark(text: str) -> None:
    read = read_file("clients.csv", text.encode("utf-8"))
    assert read.headers == ["Client name", "Client email"]
    assert read.rows == [
        (2, ["Avery Lin", "avery@example.com"]),
        (4, ["Roe, Sam", "sam@example.com"]),
    ]


def test_rows_left_out_are_written_with_the_templates_headers() -> None:
    data = write_rows(COLUMNS[:2], [["Avery Lin", "avery@example.com"]])
    read = read_file("left-out.csv", data)
    assert read.headers == ["Client name *", "Client email *"]
    assert read.rows == [(2, ["Avery Lin", "avery@example.com"])]


def test_a_file_over_the_row_limit_is_refused() -> None:
    lines = ["Client name,Client email"] + [f"n{n},n{n}@example.com" for n in range(MAX_ROWS + 1)]
    with pytest.raises(TooManyRows):
        read_file("many.csv", "\n".join(lines).encode())


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("clients.xlsx", b"not a spreadsheet"),
        ("clients.xlsx", b"PK\x03\x04 truncated"),
        ("clients.csv", b"\x00\x01\x02 binary"),
        ("clients.csv", b"x" * (5 * 1024 * 1024 + 1)),
    ],
)
def test_a_file_that_is_not_a_spreadsheet_is_refused(name: str, data: bytes) -> None:
    with pytest.raises(UnreadableFile):
        read_file(name, data)


def test_a_file_with_only_headers_is_empty() -> None:
    with pytest.raises(EmptyFile):
        read_file("clients.csv", b"Client name,Client email\n")
