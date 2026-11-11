"""A bulk send's sheet: one row per envelope (Bulk send LLD §4). Pure.

A sheet is a second way to fill in the send form. Its columns are what the form asks per envelope;
a row's cells are turned into the same ``SendRequest`` the send dialog makes and judged by the same
``plan_send``, so a row is valid exactly when a single send of the same data would be (NFR-1).
What this module adds is the translation: form to columns, cells to a request, and a refusal's
items back to the cells they came from.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from signora.kernel.errors import ValidationFailed
from signora.modules.envelopes.errors import NobodySigns
from signora.modules.envelopes.form import Colleague, FormField, Option, SendForm
from signora.modules.envelopes.sending import (
    DEFAULT_ZONE,
    MAX_COPIES,
    CopyIn,
    CountersignerIn,
    Plan,
    SendRequest,
    SettingsIn,
    plan_send,
)

MAX_ROWS = 1000
MAX_COLUMNS = 500
# A cell holds at most what a field's value may (sending.ValueIn), and one character more, so a
# value over the limit is still seen to be over it and named on its cell.
CELL_MAX = 2001
KEY_MAX = 120


def clean_cell(text: str) -> str:
    """A cell's text without what no value should carry: control characters (a NUL the database
    cannot store, an escape sequence, a line break that could start a new header in an email)
    become spaces, and the text is cut at the cell limit. The one definition, for a file's cells
    and for rows sent back by the browser."""
    cleaned = "".join(" " if (ord(ch) < 32 or 127 <= ord(ch) < 160) else ch for ch in text)
    return cleaned.strip()[:CELL_MAX]


Kind = Literal["text", "email", "date", "choice", "checkbox", "number"]
Level = Literal["error", "warning"]

_NUMBERS = frozenset({"number", "currency", "percent"})
_DATES = frozenset({"date", "date_of_birth"})
_TICKED = frozenset({"yes", "true", "x", "1", "y"})
_NOT_TICKED = frozenset({"no", "false", "0", "n", ""})

SAME_PERSON = (
    "The same person as another party in this row. Use another email, or send this one by itself"
)


class Column(BaseModel):
    """One thing a row gives. ``key`` names it for the life of the sheet; ``header`` is what the
    sender reads at the top of the column, the label the send dialog shows."""

    key: str
    header: str
    kind: Kind
    required: bool
    options: list[Option] = Field(default_factory=list)  # a choice's, or the colleagues to pick


class CellProblem(BaseModel):
    """What is wrong with a cell, in words. A warning is shown but does not stop the send."""

    key: str
    message: str
    level: Level = "error"


class RowIn(BaseModel):
    """A row as it is given: its number in the file and what its cells hold."""

    model_config = ConfigDict(extra="forbid")

    row_no: int = Field(ge=1, le=1_000_000)  # the file's row number, as the sender sees it
    cells: dict[
        Annotated[str, StringConstraints(max_length=KEY_MAX)],
        Annotated[str, StringConstraints(max_length=20_000)],
    ] = Field(max_length=MAX_COLUMNS)

    @field_validator("cells")
    @classmethod
    def _clean(cls, cells: dict[str, str]) -> dict[str, str]:
        return {key: clean_cell(text) for key, text in cells.items()}


class Row(BaseModel):
    """A row as it is judged: the same, with what is wrong with it."""

    row_no: int
    cells: dict[str, str]
    problems: list[CellProblem]


class Sheet(BaseModel):
    columns: list[Column]
    rows: list[Row]
    # What is wrong with the batch as a whole (a copy recipient's email, say), each said once.
    problems: list[str] = Field(default_factory=list)


class BatchDefaults(BaseModel):
    """What is chosen once for every row (FR-7): a row's own countersigner or setting replaces
    the matching one here."""

    model_config = ConfigDict(extra="forbid")

    countersigners: list[CountersignerIn] = Field(default_factory=list, max_length=20)
    copies: list[CopyIn] = Field(default_factory=list, max_length=MAX_COPIES)
    settings: SettingsIn
    time_zone: str = Field(default=DEFAULT_ZONE, max_length=64)


# --- columns --------------------------------------------------------------------------------------


def signer_key(party_id: uuid.UUID, part: Literal["name", "email"]) -> str:
    return f"signer:{party_id}:{part}"


def countersigner_key(party_id: uuid.UUID) -> str:
    return f"countersigner:{party_id}"


def field_key(field_id: uuid.UUID) -> str:
    return f"field:{field_id}"


def setting_key(name: str) -> str:
    return f"setting:{name}"


def kind_of(holds: str) -> Kind:
    """Which input a field's column is: the send dialog's own for that type."""
    if holds == "email":
        return "email"
    if holds in _DATES:
        return "date"
    if holds == "choice":
        return "choice"
    if holds == "checkbox":
        return "checkbox"
    if holds in _NUMBERS:
        return "number"
    return "text"


def _unique(headers: list[str]) -> list[str]:
    """Headers as given, a repeated one numbered ("Address", "Address (2)"), so each column can
    be found by its header alone."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for header in headers:
        count = seen.get(header.casefold(), 0) + 1
        seen[header.casefold()] = count
        out.append(header if count == 1 else f"{header} ({count})")
    return out


def columns_of(form: SendForm) -> list[Column]:
    """What a row gives for this form (§4.1): each signer's name and email, each countersigner
    party's colleague, then every field the sender may fill. O(P + F)."""
    party_label = {signer.party_id: signer.label for signer in form.signers}
    party_label.update({party.party_id: party.label for party in form.countersigners})
    labels = [item.label.casefold() for item in form.fields if item.from_recipient is None]
    repeated = {label for label in labels if labels.count(label) > 1}
    colleagues = [
        Option(value=person.email, text=f"{person.name} · {person.email}")
        for person in form.colleagues
    ]

    columns: list[Column] = []
    for signer in form.signers:
        columns.append(
            Column(
                key=signer_key(signer.party_id, "name"),
                header=f"{signer.label} name",
                kind="text",
                required=True,
            )
        )
        columns.append(
            Column(
                key=signer_key(signer.party_id, "email"),
                header=f"{signer.label} email",
                kind="email",
                required=True,
            )
        )
    for party in form.countersigners:
        columns.append(
            Column(
                key=countersigner_key(party.party_id),
                header=f"{party.label} countersigner",
                kind="choice",
                required=False,
                options=colleagues,
            )
        )
    for item in form.fields:
        if item.from_recipient is not None:
            continue  # the signer's own name or email fills it; never asked (form.py)
        header = item.label
        if header.casefold() in repeated and item.party_id in party_label:
            header = f"{party_label[item.party_id]}: {header}"
        columns.append(
            Column(
                key=field_key(item.id),
                header=header,
                kind=kind_of(item.holds),
                required=item.required,
                options=item.options,
            )
        )
    for column, header in zip(columns, _unique([c.header for c in columns]), strict=True):
        column.header = header
    return columns


# A row's own settings (§4.1): not in the downloaded file, recognised when a sender adds them.
SETTING_COLUMNS: tuple[Column, ...] = (
    Column(
        key=setting_key("require_email_code"), header="Email code", kind="checkbox", required=False
    ),
    Column(
        key=setting_key("reminder_interval_hours"),
        header="Remind every (hours)",
        kind="number",
        required=False,
    ),
    Column(
        key=setting_key("max_reminders"), header="Reminders at most", kind="number", required=False
    ),
    Column(
        key=setting_key("expiry_days"), header="Expires after (days)", kind="number", required=False
    ),
)


def known_columns(form: SendForm) -> list[Column]:
    """Every column a file for this form may have: what it asks, then the optional settings."""
    return [*columns_of(form), *SETTING_COLUMNS]


def header_text(column: Column) -> str:
    """A column's header as written in a file: a required one ends with a star."""
    return f"{column.header} *" if column.required else column.header


def _plain(header: str) -> str:
    """A header as compared: without its star, case or extra spaces."""
    return " ".join(header.replace("*", " ").split()).casefold()


@dataclass(frozen=True)
class Matched:
    """A file's header row read against the known columns: for each of the file's columns the
    column it is (or ``None`` for an empty header), the known columns it uses in file order, and
    what is wrong with the file as a whole."""

    keys: list[str | None]
    columns: list[Column]
    problems: list[str]


def match_headers(headers: Sequence[str], known: Sequence[Column]) -> Matched:
    by_header = {_plain(column.header): column for column in known}
    keys: list[str | None] = []
    used: dict[str, Column] = {}
    problems: list[str] = []
    for header in headers:
        if not header.strip():
            keys.append(None)
            continue
        column = by_header.get(_plain(header))
        if column is None:
            shown = clean_cell(header)[:80]
            problems.append(f'This file has a column "{shown}" that this template does not ask for')
            keys.append(None)
        elif column.key in used:
            problems.append(f'The column "{column.header}" is in this file twice')
            keys.append(None)
        else:
            used[column.key] = column
            keys.append(column.key)
    # The sheet's columns in the form's own order, whatever order the file has them in. A
    # required column the file lacks is still one of them, empty in every row, so it is filled in
    # where the problems are shown rather than by going back to the file.
    columns = [column for column in known if column.key in used or column.required]
    return Matched(keys, columns, problems)


# --- a row ----------------------------------------------------------------------------------------


def _ticked(text: str) -> bool | None:
    plain = text.strip().casefold()
    if plain in _TICKED:
        return True
    if plain in _NOT_TICKED:
        return False
    return None


def _option(text: str, options: Sequence[Option]) -> str:
    """A choice as its option's value, given as the value or as the option's words; anything else
    is passed on as typed, for the single send's check to refuse in its own words."""
    plain = text.strip().casefold()
    for option in options:
        if plain in (option.value.casefold(), option.text.strip().casefold()):
            return option.value
    return text.strip()


def _value(item: FormField, text: str) -> str:
    """A field's cell as the send dialog's input would hold it (§4.2)."""
    kind = kind_of(item.holds)
    if kind == "checkbox":
        ticked = _ticked(text)
        if ticked is None:
            return text.strip()  # refused by the single send's check
        return "true" if ticked else ""
    if kind == "choice":
        return _option(text, item.options)
    return text.strip()


_SETTING_LIMITS = {
    "reminder_interval_hours": "Give hours as a whole number from 1 to 720",
    "max_reminders": "Give a whole number from 0 to 20",
    "expiry_days": "Give days as a whole number from 1 to 365",
}


def _settings(
    cells: Mapping[str, str], defaults: SettingsIn, problems: list[CellProblem]
) -> SettingsIn:
    """The batch's settings with this row's own in place of them (FR-7)."""
    changed: dict[str, object] = {}
    code = cells.get(setting_key("require_email_code"), "").strip()
    if code:
        ticked = _ticked(code)
        if ticked is None:
            problems.append(
                CellProblem(key=setting_key("require_email_code"), message="Give yes or no")
            )
        else:
            changed["require_email_code"] = ticked
    for name, message in _SETTING_LIMITS.items():
        raw = cells.get(setting_key(name), "").strip()
        if not raw:
            continue
        if raw.isascii() and raw.isdigit():
            changed[name] = int(raw)
        else:
            problems.append(CellProblem(key=setting_key(name), message=message))
    if not changed:
        return defaults
    try:
        return SettingsIn.model_validate({**defaults.model_dump(), **changed})
    except ValidationError as error:
        for issue in error.errors():
            name = str(issue["loc"][0]) if issue["loc"] else ""
            problems.append(
                CellProblem(key=setting_key(name), message=_SETTING_LIMITS.get(name, issue["msg"]))
            )
        return defaults


@dataclass(frozen=True)
class Checked:
    """A row judged: what is wrong with it, and when nothing is, the request to send it with and
    the plan a single send would write."""

    problems: list[CellProblem]
    general: list[str]  # the batch's own problems this row met (said once per sheet)
    request: SendRequest | None
    plan: Plan | None


def _request_problems(error: ValidationError, form: SendForm) -> list[CellProblem]:
    """A request the API itself would refuse (an empty or over-long name, say), on its cell."""
    problems: list[CellProblem] = []
    for issue in error.errors():
        loc = issue["loc"]
        key = ""
        if len(loc) >= 3 and loc[0] == "signers" and isinstance(loc[1], int):
            key = signer_key(
                form.signers[loc[1]].party_id, "email" if loc[2] == "email" else "name"
            )
        elif len(loc) >= 2 and loc[0] == "values" and isinstance(loc[1], int):
            key = "values"  # replaced below with the field's key by the caller's order
        limit = issue.get("ctx", {}).get("max_length")
        if issue["type"] == "string_too_short":
            message = "Enter an email address" if key.endswith(":email") else "Enter a name"
        elif issue["type"] == "string_too_long" and limit:
            message = f"Use {limit} or fewer characters"
        else:
            message = str(issue["msg"])
        problems.append(CellProblem(key=key, message=message))
    return problems


def check_row(
    form: SendForm,
    cells: Mapping[str, str],
    defaults: BatchDefaults,
    *,
    normalize_email: Callable[[str], str],
) -> Checked:
    """One row as a single send would judge it. O(P + F)."""
    problems: list[CellProblem] = []
    general: list[str] = []

    def add(key: str, message: str) -> None:
        # The first thing said about a cell stands: a later item about the same cell is a
        # consequence of it (a colleague that is not one, then "choose who countersigns").
        if all(problem.key != key for problem in problems):
            problems.append(CellProblem(key=key, message=message))

    # Signers: every party of the form, so a missing one is named on its own cells.
    signers: list[dict[str, object]] = []
    for signer in form.signers:
        signers.append(
            {
                "party_id": signer.party_id,
                "name": cells.get(signer_key(signer.party_id, "name"), "").strip(),
                "email": cells.get(signer_key(signer.party_id, "email"), "").strip(),
            }
        )

    # Countersigners: the row's own colleague, or the batch's default for that party.
    by_email = {person.email.casefold(): person for person in form.colleagues}
    default_of = {choice.party_id: choice.user_id for choice in defaults.countersigners}
    countersigners: list[dict[str, object]] = []
    for party in form.countersigners:
        own = cells.get(countersigner_key(party.party_id), "").strip()
        if own:
            colleague = by_email.get(own.casefold())
            if colleague is None:
                add(countersigner_key(party.party_id), "Not a colleague's email")
            else:
                countersigners.append({"party_id": party.party_id, "user_id": colleague.user_id})
        elif party.party_id in default_of:
            countersigners.append(
                {"party_id": party.party_id, "user_id": default_of[party.party_id]}
            )

    values: list[dict[str, object]] = []
    value_fields: list[uuid.UUID] = []
    for item in form.fields:
        if item.from_recipient is not None:
            continue
        text = _value(item, cells.get(field_key(item.id), ""))
        if text:
            values.append({"field_id": item.id, "value": text})
            value_fields.append(item.id)

    settings = _settings(cells, defaults.settings, problems)
    try:
        request = SendRequest.model_validate(
            {
                "version_id": form.version_id,
                "signers": signers,
                "countersigners": countersigners,
                "copies": [copy.model_dump() for copy in defaults.copies],
                "values": values,
                "settings": settings.model_dump(),
                "time_zone": defaults.time_zone,
            }
        )
    except ValidationError as error:
        for problem in _request_problems(error, form):
            if problem.key == "values":
                continue  # a value over the length limit: named below by its field
            if problem.key:
                add(problem.key, problem.message)
            else:
                general.append(problem.message)
        for issue in error.errors():
            loc = issue["loc"]
            if len(loc) >= 2 and loc[0] == "values" and isinstance(loc[1], int):
                add(field_key(value_fields[loc[1]]), "Use 2000 or fewer characters")
        return Checked(problems, general, None, None)

    colleagues: dict[uuid.UUID, Colleague] = {person.user_id: person for person in form.colleagues}
    try:
        plan = plan_send(form, request, colleagues=colleagues, normalize_email=normalize_email)
    except ValidationFailed as refused:
        signer_parties = {signer.party_id for signer in form.signers}
        for item_error in refused.field_errors:
            key = _cell_of(item_error.field, request, signer_parties)
            if key is None:
                general.append(item_error.message)
            else:
                add(key, item_error.message)
        return Checked(problems, general, None, None)

    if plan.shared_emails:
        shared = set(plan.shared_emails)
        for person in plan.signers:
            if person.email in shared and person.party_id is not None:
                add(signer_key(person.party_id, "email"), SAME_PERSON)
        for person in plan.countersigners:
            if person.email in shared and person.party_id is not None:
                add(countersigner_key(person.party_id), SAME_PERSON)
    if problems:
        return Checked(problems, general, None, None)
    return Checked([], general, request, plan)


def _cell_of(path: str, request: SendRequest, signer_parties: set[uuid.UUID]) -> str | None:
    """The cell a single send's refusal is about, from the item it names (``sending.plan_send``):
    ``signers[2].email``, ``fields.<id>``, ``parties.<id>``. ``None``: it is about the batch."""
    head, _, rest = path.partition(".")
    if head.startswith("signers[") and head.endswith("]"):
        signer = request.signers[int(head[len("signers[") : -1])]
        return signer_key(signer.party_id, "email" if rest == "email" else "name")
    if head.startswith("countersigners[") and head.endswith("]"):
        chosen = request.countersigners[int(head[len("countersigners[") : -1])]
        return countersigner_key(chosen.party_id)
    if head == "fields":
        return field_key(uuid.UUID(rest))
    if head == "parties":
        party_id = uuid.UUID(rest)
        if party_id in signer_parties:
            return signer_key(party_id, "name")
        return countersigner_key(party_id)
    return None


# --- the sheet ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckedSheet:
    sheet: Sheet
    # Each row that may be sent, in file order: its number, a name for it, its request.
    sendable: list[tuple[int, str, SendRequest]]

    @property
    def blocked(self) -> bool:
        """Whether anything stops the send: a batch problem, or an error on any row."""
        return bool(self.sheet.problems) or any(
            problem.level == "error" for row in self.sheet.rows for problem in row.problems
        )


def _label(plan: Plan) -> str:
    """Who a row is for, to name it once its typed data is gone: its first signer (or, with no
    signer, its first countersigner)."""
    person = (plan.signers or plan.countersigners)[0]
    return f"{person.name} · {person.email}"


def check_rows(
    form: SendForm,
    columns: Sequence[Column],
    rows: Sequence[RowIn],
    defaults: BatchDefaults,
    *,
    normalize_email: Callable[[str], str],
) -> CheckedSheet:
    """Every row judged, then the rows against each other (FR-6). O(R · (P + F)): one pass over
    the rows and one map from signer email to the rows that send to it."""
    if not form.signers and not form.countersigners:
        raise NobodySigns
    general: dict[str, None] = {}
    checked: list[Row] = []
    sendable: list[tuple[int, str, SendRequest]] = []
    sends_to: dict[str, list[int]] = {}  # a signer's email -> indexes of the rows sending to it
    signer_emails: list[list[tuple[uuid.UUID, str]]] = []

    for index, row in enumerate(rows):
        result = check_row(form, row.cells, defaults, normalize_email=normalize_email)
        general.update(dict.fromkeys(result.general))
        checked.append(Row(row_no=row.row_no, cells=dict(row.cells), problems=result.problems))
        emails: list[tuple[uuid.UUID, str]] = []
        if result.plan is not None and result.request is not None:
            sendable.append((row.row_no, _label(result.plan), result.request))
            for person in result.plan.signers:
                if person.party_id is not None:
                    emails.append((person.party_id, person.email))
                    sends_to.setdefault(person.email, []).append(index)
        signer_emails.append(emails)

    for index, emails in enumerate(signer_emails):
        for party_id, address in emails:
            others = [checked[other].row_no for other in sends_to[address] if other != index]
            if others:
                listed = ", ".join(str(number) for number in others[:3])
                more = "" if len(others) <= 3 else f" and {len(others) - 3} more"
                noun = "row" if len(others) == 1 else "rows"
                checked[index].problems.append(
                    CellProblem(
                        key=signer_key(party_id, "email"),
                        message=f"Also in {noun} {listed}{more}",
                        level="warning",
                    )
                )
    # A problem is always on a column the sheet shows: one about a column the file did not have
    # (a field that is required only once another is filled) brings that column in.
    shown = {column.key for column in columns}
    named = {problem.key for row in checked for problem in row.problems}
    extra = [c for c in known_columns(form) if c.key in named and c.key not in shown]
    return CheckedSheet(
        Sheet(columns=[*columns, *extra], rows=checked, problems=list(general)), sendable
    )
