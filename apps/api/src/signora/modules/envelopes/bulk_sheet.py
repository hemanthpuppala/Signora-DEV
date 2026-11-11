"""A bulk send's sheet: one row per envelope (Bulk send LLD §4). Pure.

A sheet is a second way to fill in the send form. Its columns are what the form asks per envelope;
a row's cells are turned into the same ``SendRequest`` the send dialog makes and judged by the same
``plan_send``, so a row is valid exactly when a single send of the same data would be (NFR-1).
What this module adds is the translation: form to columns, cells to a request, and a refusal's
items back to the cells they came from.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
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
    Plan,
    SendRequest,
    SettingsIn,
    one_line,
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
    become spaces, as in a single send (``sending.one_line``), and the text is cut at the cell
    limit. For a file's cells and for rows sent back by the browser."""
    return one_line(text).strip()[:CELL_MAX]


Kind = Literal["text", "email", "date", "choice", "checkbox", "number"]
Level = Literal["error", "warning"]

_NUMBERS = frozenset({"number", "currency", "percent"})
_DATES = frozenset({"date", "date_of_birth"})
_TICKED = frozenset({"yes", "true", "x", "1", "y"})
_NOT_TICKED = frozenset({"no", "false", "0", "n", ""})
TICKED = "yes"  # how a ticked box is written in a cell the sheet gives back

SAME_PERSON = (
    "The same person as another party in this row. Use another email, or send this one by itself"
)
NOT_A_COLLEAGUE = "Not a colleague's email"


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
    """A row as it is judged: its cells as they are read (a choice as its option's value, a tick
    as ``yes``, a colleague as their email), with what is wrong with it. Whoever shows the row
    shows these cells and needs no reading rules of their own."""

    row_no: int
    cells: dict[str, str]
    problems: list[CellProblem]


class Sheet(BaseModel):
    columns: list[Column]
    rows: list[Row]
    # What is wrong with the batch as a whole (a copy recipient's email, say), each said once.
    problems: list[str] = Field(default_factory=list)


class BatchDefaults(BaseModel):
    """What is chosen once for every row (FR-7); a row's own setting replaces the matching one
    here. Who countersigns is not chosen here: every row names its own."""

    model_config = ConfigDict(extra="forbid")

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


def _plain(header: str) -> str:
    """A header as compared: without its star, case or extra spaces."""
    return " ".join(header.replace("*", " ").split()).casefold()


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
_RESERVED = frozenset(_plain(column.header) for column in SETTING_COLUMNS)


def _unique(headers: Sequence[str]) -> list[str]:
    """Headers as given, one that reads the same as an earlier one numbered ("Address",
    "Address (2)"), so each column is found by its header alone. "The same" is the reading
    ``match_headers`` uses, and the optional settings' headers are taken already. O(n)."""
    taken = set(_RESERVED)
    count: Counter[str] = Counter()
    out: list[str] = []
    for header in headers:
        candidate = header
        while _plain(candidate) in taken:
            count[_plain(header)] += 1
            candidate = f"{header} ({count[_plain(header)] + 1})"
        taken.add(_plain(candidate))
        out.append(candidate)
    return out


def columns_of(form: SendForm) -> list[Column]:
    """What a row gives for this form (§4.1): each signer's name and email, each countersigner
    party's colleague, then every field the sender may fill. O(P + F + C)."""
    party_label = {signer.party_id: signer.label for signer in form.signers}
    party_label.update({party.party_id: party.label for party in form.countersigners})
    asked = [item for item in form.fields if item.from_recipient is None]
    times = Counter(_plain(item.label) for item in asked)
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
                required=True,  # every envelope names who countersigns it
                options=colleagues,
            )
        )
    for item in asked:
        header = item.label
        if times[_plain(header)] > 1 and item.party_id in party_label:
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


def known_columns(form: SendForm) -> list[Column]:
    """Every column a file for this form may have: what it asks, then the optional settings."""
    return [*columns_of(form), *SETTING_COLUMNS]


def header_text(column: Column) -> str:
    """A column's header as written in a file: a required one ends with a star."""
    return f"{column.header} *" if column.required else column.header


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


def _limits(name: str) -> tuple[int, int]:
    """A numeric setting's range, read from the one place it is defined (``SettingsIn``)."""
    low = high = 0
    for rule in SettingsIn.model_fields[name].metadata:
        low = getattr(rule, "ge", low)
        high = getattr(rule, "le", high)
    return low, high


_NUMERIC_SETTINGS = ("reminder_interval_hours", "max_reminders", "expiry_days")


def _out_of_range(name: str) -> str:
    low, high = _limits(name)
    return f"Enter a whole number from {low} to {high}"


def _settings(
    cells: Mapping[str, str], defaults: SettingsIn, say: Callable[[str, str], None]
) -> SettingsIn:
    """The batch's settings with this row's own in place of them (FR-7)."""
    changed: dict[str, object] = {}
    code = cells.get(setting_key("require_email_code"), "").strip()
    if code:
        ticked = _ticked(code)
        if ticked is None:
            say(setting_key("require_email_code"), "Give yes or no")
        else:
            changed["require_email_code"] = ticked
    for name in _NUMERIC_SETTINGS:
        raw = cells.get(setting_key(name), "").strip()
        if not raw:
            continue
        low, high = _limits(name)
        if raw.isascii() and raw.isdigit() and low <= int(raw) <= high:
            changed[name] = int(raw)
        else:
            say(setting_key(name), _out_of_range(name))
    return defaults.model_copy(update=changed) if changed else defaults


@dataclass(frozen=True)
class Lookups:
    """What every row of a sheet is read against, built once for the sheet: O(P + F + C)."""

    by_email: dict[str, Colleague]
    by_id: dict[uuid.UUID, Colleague]
    colleague_options: list[Option]
    signer_parties: frozenset[uuid.UUID]
    asked: list[FormField]  # the fields a row may give (not the signer's own name or email)

    @staticmethod
    def of(form: SendForm) -> Lookups:
        return Lookups(
            by_email={person.email.casefold(): person for person in form.colleagues},
            by_id={person.user_id: person for person in form.colleagues},
            colleague_options=[
                Option(value=person.email, text=f"{person.name} · {person.email}")
                for person in form.colleagues
            ],
            signer_parties=frozenset(signer.party_id for signer in form.signers),
            asked=[item for item in form.fields if item.from_recipient is None],
        )


@dataclass
class Checked:
    """A row judged: its cells as read, what is wrong with it, and when nothing is, the request
    to send it with and the plan a single send would write."""

    cells: dict[str, str]
    problems: list[CellProblem] = field(default_factory=list)
    general: list[str] = field(default_factory=list)  # the batch's own problems this row met
    request: SendRequest | None = None
    plan: Plan | None = None


def check_row(
    form: SendForm,
    cells: Mapping[str, str],
    defaults: BatchDefaults,
    *,
    normalize_email: Callable[[str], str],
    lookups: Lookups | None = None,
) -> Checked:
    """One row as a single send would judge it. O(P + F) given the sheet's lookups."""
    known = lookups or Lookups.of(form)
    result = Checked(cells=dict(cells))
    said: set[str] = set()

    def say(key: str, message: str) -> None:
        # The first thing said about a cell stands: a later item about the same cell is a
        # consequence of it (a colleague that is not one, then "choose who countersigns").
        if key not in said:
            said.add(key)
            result.problems.append(CellProblem(key=key, message=message))

    # Signers: every party of the form, so a missing one is named on its own cells.
    signers = [
        {
            "party_id": signer.party_id,
            "name": cells.get(signer_key(signer.party_id, "name"), "").strip(),
            "email": cells.get(signer_key(signer.party_id, "email"), "").strip(),
        }
        for signer in form.signers
    ]

    # Countersigners: the colleague the row names, by email or as the list shows them.
    countersigners: list[dict[str, object]] = []
    for party in form.countersigners:
        key = countersigner_key(party.party_id)
        given = _option(cells.get(key, ""), known.colleague_options)
        if not given:
            continue  # the single send says who is missing, on this cell
        colleague = known.by_email.get(given.casefold())
        if colleague is None:
            say(key, NOT_A_COLLEAGUE)
        else:
            result.cells[key] = colleague.email
            countersigners.append({"party_id": party.party_id, "user_id": colleague.user_id})

    values: list[dict[str, object]] = []
    value_fields: list[uuid.UUID] = []
    for item in known.asked:
        key = field_key(item.id)
        text = _value(item, cells.get(key, ""))
        kind = kind_of(item.holds)
        if kind == "checkbox" and text in ("true", ""):
            result.cells[key] = TICKED if text else ""
        elif kind == "choice":
            result.cells[key] = text
        if text:
            values.append({"field_id": item.id, "value": text})
            value_fields.append(item.id)

    settings = _settings(cells, defaults.settings, say)
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
        _say_request_problems(error, form, value_fields, say, result.general)
        return result

    try:
        plan = plan_send(form, request, colleagues=known.by_id, normalize_email=normalize_email)
    except ValidationFailed as refused:
        for item_error in refused.field_errors:
            cell = _cell_of(item_error.field, request, known.signer_parties)
            if cell is None:
                result.general.append(item_error.message)
            else:
                say(cell, item_error.message)
        return result

    if plan.shared_emails:
        shared = set(plan.shared_emails)
        for person in plan.signers:
            if person.email in shared and person.party_id is not None:
                say(signer_key(person.party_id, "email"), SAME_PERSON)
        for person in plan.countersigners:
            if person.email in shared and person.party_id is not None:
                say(countersigner_key(person.party_id), SAME_PERSON)
    if not result.problems:
        result.request, result.plan = request, plan
    return result


def _say_request_problems(
    error: ValidationError,
    form: SendForm,
    value_fields: Sequence[uuid.UUID],
    say: Callable[[str, str], None],
    general: list[str],
) -> None:
    """A request the API itself would refuse (an empty or over-long name, a value over the
    length limit), each on its cell."""
    for issue in error.errors():
        loc = issue["loc"]
        limit = issue.get("ctx", {}).get("max_length")
        too_long = f"Use {limit} or fewer characters" if limit else str(issue["msg"])
        if len(loc) >= 3 and loc[0] == "signers" and isinstance(loc[1], int):
            part: Literal["name", "email"] = "email" if loc[2] == "email" else "name"
            if issue["type"] == "string_too_short":
                message = "Enter an email address" if part == "email" else "Enter a name"
            else:
                message = too_long
            say(signer_key(form.signers[loc[1]].party_id, part), message)
        elif len(loc) >= 2 and loc[0] == "values" and isinstance(loc[1], int):
            say(field_key(value_fields[loc[1]]), too_long)
        else:
            general.append(str(issue["msg"]))


def _cell_of(path: str, request: SendRequest, signer_parties: frozenset[uuid.UUID]) -> str | None:
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


def _also_in(row_numbers: Sequence[int], own: int) -> str:
    """ "Also in rows 3, 4, 5 and 12 more": the first three other rows and how many beyond them.
    O(1): only the first four of the group are looked at."""
    others = len(row_numbers) - 1
    listed = [number for number in row_numbers[:4] if number != own][:3]
    more = "" if others <= 3 else f" and {others - 3} more"
    noun = "row" if others == 1 else "rows"
    return f"Also in {noun} {', '.join(str(number) for number in listed)}{more}"


def check_rows(
    form: SendForm,
    columns: Sequence[Column],
    rows: Sequence[RowIn],
    defaults: BatchDefaults,
    *,
    normalize_email: Callable[[str], str],
) -> CheckedSheet:
    """Every row judged, then the rows against each other (FR-6). O(P + F + C) once for the
    sheet, then O(P + F) a row: one pass over the rows, and one map from a signer's email to the
    rows that send to it."""
    if not form.signers and not form.countersigners:
        raise NobodySigns
    lookups = Lookups.of(form)
    general: dict[str, None] = {}
    checked: list[Row] = []
    sendable: list[tuple[int, str, SendRequest]] = []
    sends_to: dict[str, list[int]] = {}  # a signer's email -> the numbers of the rows sending to it
    signer_emails: list[list[tuple[uuid.UUID, str]]] = []

    for row in rows:
        result = check_row(
            form, row.cells, defaults, normalize_email=normalize_email, lookups=lookups
        )
        general.update(dict.fromkeys(result.general))
        checked.append(Row(row_no=row.row_no, cells=result.cells, problems=result.problems))
        emails: list[tuple[uuid.UUID, str]] = []
        if result.plan is not None and result.request is not None:
            sendable.append((row.row_no, _label(result.plan), result.request))
            for person in result.plan.signers:
                if person.party_id is not None:
                    emails.append((person.party_id, person.email))
                    sends_to.setdefault(person.email, []).append(row.row_no)
        signer_emails.append(emails)

    for judged, emails in zip(checked, signer_emails, strict=True):
        for party_id, address in emails:
            group = sends_to[address]
            if len(group) > 1:
                judged.problems.append(
                    CellProblem(
                        key=signer_key(party_id, "email"),
                        message=_also_in(group, judged.row_no),
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
