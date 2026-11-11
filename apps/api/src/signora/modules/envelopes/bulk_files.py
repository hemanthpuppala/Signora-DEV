"""A bulk send's files (Bulk send LLD §4.1, §4.2): the spreadsheet made for a version, and a
filled one read back, as XLSX or CSV.

Reading gives text: every cell as the send dialog's input would hold it (a date cell as an ISO
date, a number as its digits), so nothing downstream knows which format the file was. A file is
untrusted: it is read as a stream, stopped at the row limit, and its XML is parsed by defusedxml
(openpyxl uses it when it is installed), which refuses entity expansion.
"""

from __future__ import annotations

import csv
import io
import uuid
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from signora.modules.envelopes.bulk_sheet import MAX_ROWS, Column, header_text
from signora.modules.envelopes.errors import EmptyFile, TooManyRows, UnreadableFile

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_COLUMNS = 500
ROWS_SHEET = "Envelopes"
GUIDE_SHEET = "How to fill this in"
VERSION_SHEET = "_signora"  # hidden: the version the file was made for
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_LIST_LIMIT = 255  # a cell's list of allowed values, as one formula string (the format's limit)
_GUIDE = {
    "text": "Text",
    "email": "An email address",
    "date": "A date, as YYYY-MM-DD",
    "choice": "One of the options",
    "checkbox": "yes or no",
    "number": "A number",
}


@dataclass(frozen=True)
class FileRows:
    """A file as read: its header row, each row that holds anything with its number in the file,
    and (an XLSX made here) the version it was made for."""

    headers: list[str]
    rows: list[tuple[int, list[str]]]
    version_id: uuid.UUID | None


# --- writing --------------------------------------------------------------------------------------


def _allowed_values(column: Column) -> list[str] | None:
    """The values a cell may be restricted to, when they fit the format's one-string list."""
    if column.kind == "checkbox":
        return ["yes", "no"]
    if column.kind != "choice" or not column.options:
        return None
    # A colleague is picked by email; a choice by its option's words, as the dialog shows it.
    words = [
        option.value if column.key.startswith("countersigner:") else option.text
        for option in column.options
    ]
    if any("," in word or '"' in word for word in words) or len(",".join(words)) > _LIST_LIMIT:
        return None
    return words


def _guide_line(column: Column) -> tuple[str, str, str]:
    what = _GUIDE[column.kind]
    if column.key.startswith("countersigner:"):
        what = "A colleague's email. Leave empty to use the one chosen when sending"
    elif column.kind == "choice" and column.options:
        what = "One of: " + ", ".join(option.text for option in column.options)
    return header_text(column), "Required" if column.required else "Optional", what


def write_template(columns: Sequence[Column], *, version_id: uuid.UUID, title: str) -> bytes:
    """The spreadsheet for a version (FR-1): one column per thing a row gives, with choices and
    dates restricted in the cells, and a second sheet that says what each column takes."""
    book = Workbook()
    if book.active is not None:
        book.remove(book.active)  # the workbook's own first sheet; ours are named
    sheet: Worksheet = book.create_sheet(ROWS_SHEET)
    last_row = MAX_ROWS + 1
    for index, column in enumerate(columns, start=1):
        letter = get_column_letter(index)
        cell = sheet.cell(row=1, column=index, value=header_text(column))
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        sheet.column_dimensions[letter].width = max(16, min(40, len(column.header) + 4))
        cells = f"{letter}2:{letter}{last_row}"
        allowed = _allowed_values(column)
        if allowed is not None:
            rule = DataValidation(
                type="list", formula1='"' + ",".join(allowed) + '"', allow_blank=True
            )
            rule.error = "Choose one of the listed values"
            sheet.add_data_validation(rule)
            rule.add(cells)
        elif column.kind == "date":
            rule = DataValidation(
                type="date", operator="greaterThan", formula1="1", allow_blank=True
            )
            rule.error = "Enter a date"
            sheet.add_data_validation(rule)
            rule.add(cells)
            sheet.column_dimensions[letter].number_format = "yyyy-mm-dd"
        elif column.kind in ("text", "email"):
            # Kept as typed: a ZIP code or a phone number is not a number.
            sheet.column_dimensions[letter].number_format = "@"
    sheet.freeze_panes = "A2"

    guide: Worksheet = book.create_sheet(GUIDE_SHEET)
    guide.append([title])
    guide.append(["One row is one envelope. Fill the Envelopes sheet from row 2 and upload it."])
    guide.append([])
    guide.append(["Column", "", "What to enter"])
    for column in columns:
        guide.append(list(_guide_line(column)))
    for cell in (guide["A1"], guide["A4"], guide["B4"], guide["C4"]):
        cell.font = Font(bold=True)
    guide.column_dimensions["A"].width = 36
    guide.column_dimensions["B"].width = 12
    guide.column_dimensions["C"].width = 70

    made_for: Worksheet = book.create_sheet(VERSION_SHEET)
    made_for["A1"] = str(version_id)
    made_for.sheet_state = "hidden"

    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def write_rows(columns: Sequence[Column], rows: Iterable[Sequence[str]]) -> bytes:
    """Rows as a CSV with the template's headers: the rows a sender left out (FR-5)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([header_text(column) for column in columns])
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")  # the mark lets a spreadsheet read it as UTF-8


# --- reading --------------------------------------------------------------------------------------


def _text(value: Any) -> str:
    """A cell as the text a person would have typed for it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _rows(lines: Iterator[Sequence[Any]]) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """The header row and every row under it that holds anything, numbered as in the file."""
    try:
        headers = [_text(value) for value in next(lines)]
    except StopIteration:
        raise EmptyFile from None
    if len(headers) > MAX_COLUMNS:
        raise UnreadableFile
    while headers and not headers[-1]:
        headers.pop()
    rows: list[tuple[int, list[str]]] = []
    for number, line in enumerate(lines, start=2):
        cells = [_text(value) for value in line[: len(headers)]]
        if not any(cells):
            continue
        if len(rows) >= MAX_ROWS:
            raise TooManyRows(f"This file has more than {MAX_ROWS:,} rows. Send it in parts")
        cells.extend([""] * (len(headers) - len(cells)))
        rows.append((number, cells))
    if not rows:
        raise EmptyFile
    return headers, rows


def _read_xlsx(data: bytes) -> FileRows:
    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as error:
        raise UnreadableFile from error
    try:
        names = book.sheetnames
        visible = [name for name in names if name not in (GUIDE_SHEET, VERSION_SHEET)]
        if not visible:
            raise UnreadableFile
        sheet = book[ROWS_SHEET] if ROWS_SHEET in names else book[visible[0]]
        headers, rows = _rows(sheet.iter_rows(values_only=True))
        version_id = None
        if VERSION_SHEET in names:
            first = next(book[VERSION_SHEET].iter_rows(max_row=1, max_col=1, values_only=True), ())
            try:
                version_id = uuid.UUID(_text(first[0])) if first else None
            except ValueError:
                version_id = None
        return FileRows(headers, rows, version_id)
    finally:
        book.close()


def _read_csv(data: bytes) -> FileRows:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")  # a spreadsheet's older export
    sample = text[:4096]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    try:
        headers, rows = _rows(iter(csv.reader(io.StringIO(text), dialect)))
    except csv.Error as error:
        raise UnreadableFile from error
    return FileRows(headers, rows, None)


def read_file(filename: str, data: bytes) -> FileRows:
    """A filled file, as XLSX or CSV, told apart by its content (an XLSX is a ZIP), not its name
    alone."""
    if len(data) > MAX_FILE_BYTES:
        raise UnreadableFile
    if data[:4] == b"PK\x03\x04":
        return _read_xlsx(data)
    if filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
        raise UnreadableFile  # named as a spreadsheet, but not one this reads
    if b"\x00" in data[:4096]:
        raise UnreadableFile  # binary, not text
    return _read_csv(data)
