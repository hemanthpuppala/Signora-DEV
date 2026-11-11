"""A bulk send: a checked sheet written as a batch, and the job that sends its rows (Bulk send
LLD §4.4, §5).

Every row goes out through ``service.send``, the single send, as the person who sent the batch:
the same access check, the same writes, the same emails. A batch only adds what a single send has
no need of: which rows there are, and what became of each.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from signora.kernel.db import UnitOfWork
from signora.kernel.errors import DomainError, NotFound, ValidationFailed
from signora.kernel.jobs import JobContext, JobKind, JobRegistry, RecurringJob, enqueue
from signora.kernel.logging import get_logger
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.departments import get_department, load_access
from signora.modules.envelopes import service
from signora.modules.envelopes.bulk_files import FileRows, read_file, write_rows, write_template
from signora.modules.envelopes.bulk_sheet import (
    KEY_MAX,
    MAX_COLUMNS,
    MAX_ROWS,
    BatchDefaults,
    Column,
    RowIn,
    Sheet,
    check_rows,
    clean_cell,
    columns_of,
    countersigner_key,
    known_columns,
    match_headers,
)
from signora.modules.envelopes.errors import NobodySigns, OutdatedSpreadsheet, RowsNeedFixing
from signora.modules.envelopes.form import SendForm
from signora.modules.envelopes.sending import SendRequest, SettingsIn
from signora.modules.identity_access import Actor, Permission, actor_of, normalize_email

log = get_logger(__name__)

SEND_BATCH = "envelopes.send_batch"
MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=10)  # renewed while it runs; a thousand sends take about a minute
RECENT = timedelta(hours=24)
NO_ACCESS = "The person who sent this batch can no longer send from this department"
GAVE_UP = "This row could not be sent. Send it again"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckRequest(_In):
    """Rows to judge again after the sender's edits, with what is chosen once for all of them."""

    # The sheet's column keys, as upload gave them.
    columns: list[Annotated[str, StringConstraints(max_length=KEY_MAX)]] = Field(
        max_length=MAX_COLUMNS
    )
    rows: list[RowIn] = Field(max_length=MAX_ROWS)
    defaults: BatchDefaults


class BatchRequest(_In):
    version_id: uuid.UUID
    file_name: str = Field(min_length=1, max_length=255)

    @field_validator("file_name")
    @classmethod
    def _clean_name(cls, name: str) -> str:
        return clean_cell(name)[:255] or "spreadsheet"

    rows: list[RowIn] = Field(min_length=1, max_length=MAX_ROWS)
    defaults: BatchDefaults


class BatchFailure(BaseModel):
    row_no: int
    label: str
    error: str


class BatchView(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    file_name: str
    created_at: datetime
    finished_at: datetime | None
    status: Literal["sending", "finished"]
    total: int
    sent: int
    failed: int
    failures: list[BatchFailure]


# --- the sheet, for someone who may send ---------------------------------------------------------


def _form(
    session: Session, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> SendForm:
    """The send form of an approved version, for someone with edit access (as a single send)."""
    form = service.send_form(session, actor, document_id, version_id)
    if not form.signers and not form.countersigners:
        raise NobodySigns
    return form


def form_defaults(form: SendForm) -> BatchDefaults:
    """What a batch starts from: the department's settings, as the send dialog starts from them."""
    return BatchDefaults(settings=SettingsIn(**form.settings.model_dump()))


def authorize(
    session: Session, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> None:
    """Refuse whoever may not send this version, before anything of theirs is read."""
    _form(session, actor, document_id, version_id)


def template(
    session: Session, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[str, bytes]:
    """The spreadsheet for a version (FR-1) and the name to save it under."""
    form = _form(session, actor, document_id, version_id)
    data = write_template(columns_of(form), version_id=version_id, title=form.document_name)
    return f"{form.document_name} bulk send.xlsx", data


def _sheet_rows(file: FileRows, keys: Sequence[str | None], form: SendForm) -> list[RowIn]:
    """A file's rows as a sheet's. A row that does not say who countersigns takes the
    department's countersigner for that party, as the send dialog does; with none set, the cell
    stays empty and is asked for where the rows are corrected."""
    usual = {
        countersigner_key(party.party_id): party.default.email
        for party in form.countersigners
        if party.default is not None
    }
    return [
        RowIn(
            row_no=number,
            cells={
                **usual,
                **{key: cell for key, cell in zip(keys, cells, strict=False) if key and cell},
            },
        )
        for number, cells in file.rows
    ]


def parse(
    session: Session,
    actor: Actor,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    filename: str,
    data: bytes,
) -> Sheet:
    """A filled file as a sheet: its columns, its rows, and what is wrong with each (FR-2, FR-3).
    A file with the wrong columns comes back with that said and no rows."""
    form = _form(session, actor, document_id, version_id)
    file = read_file(filename, data)
    if file.version_id is not None and file.version_id != version_id:
        raise OutdatedSpreadsheet
    matched = match_headers(file.headers, known_columns(form))
    if matched.problems:
        return Sheet(columns=[], rows=[], problems=matched.problems)
    return check_rows(
        form,
        matched.columns,
        _sheet_rows(file, matched.keys, form),
        form_defaults(form),
        normalize_email=normalize_email,
    ).sheet


def _columns(form: SendForm, keys: Sequence[str]) -> list[Column]:
    wanted = set(keys)
    return [column for column in known_columns(form) if column.key in wanted]


def check(
    session: Session,
    actor: Actor,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    body: CheckRequest,
) -> Sheet:
    """The sheet judged again after edits (FR-4): the same check as at upload and at send."""
    form = _form(session, actor, document_id, version_id)
    return check_rows(
        form,
        _columns(form, body.columns),
        body.rows,
        body.defaults,
        normalize_email=normalize_email,
    ).sheet


def left_out(
    session: Session,
    actor: Actor,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    body: CheckRequest,
) -> bytes:
    """The given rows as a CSV with the template's headers (FR-5)."""
    form = _form(session, actor, document_id, version_id)
    columns = _columns(form, body.columns)
    return write_rows(
        columns, ([row.cells.get(column.key, "") for column in columns] for row in body.rows)
    )


# --- a batch -------------------------------------------------------------------------------------


def _audit(uow: UnitOfWork, actor: Actor, action: str, batch_id: uuid.UUID, **data: Any) -> None:
    record(
        uow,
        chain=AuditChain.workspace(actor.workspace_id),
        actor=AuditActor("user", actor.user_id, actor.email),
        action=action,
        subject=Subject("envelope_batch", batch_id),
        data=data,
    )


def create_batch(
    uow: UnitOfWork, *, actor: Actor, document_id: uuid.UUID, request: BatchRequest
) -> BatchView:
    """Check every row once more and, when none has a problem, write the batch and queue its job
    (§4.4). A batch with a problem writes nothing."""
    session = uow.session
    form = _form(session, actor, document_id, request.version_id)
    checked = check_rows(
        form, columns_of(form), request.rows, request.defaults, normalize_email=normalize_email
    )
    if checked.blocked or len(checked.sendable) != len(request.rows):
        raise RowsNeedFixing
    numbers = [number for number, _, _ in checked.sendable]
    if len(set(numbers)) != len(numbers):
        raise ValidationFailed([], "Two rows have the same number")
    department_id = session.execute(
        text("SELECT department_id FROM documents WHERE id = :d AND workspace_id = :w"),
        {"d": document_id, "w": actor.workspace_id},
    ).scalar_one()
    batch_id = session.execute(
        text(
            "INSERT INTO envelope_batches (workspace_id, department_id, document_id, version_id, "
            "created_by, file_name, total) VALUES (:w, :dep, :doc, :v, :u, :name, :total) "
            "RETURNING id"
        ),
        {
            "w": actor.workspace_id,
            "dep": department_id,
            "doc": document_id,
            "v": request.version_id,
            "u": actor.user_id,
            "name": request.file_name,
            "total": len(checked.sendable),
        },
    ).scalar_one()
    session.execute(
        text(
            "INSERT INTO envelope_batch_rows (batch_id, workspace_id, row_no, label, request) "
            "VALUES (:b, :w, :n, :label, CAST(:request AS jsonb))"
        ),
        [
            {
                "b": batch_id,
                "w": actor.workspace_id,
                "n": number,
                "label": label[:300],
                "request": row_request.model_dump_json(),
            }
            for number, label, row_request in checked.sendable
        ],
    )
    enqueue(session, SEND_BATCH, {"batch_id": str(batch_id)}, dedupe_key=f"{SEND_BATCH}:{batch_id}")
    _audit(
        uow,
        actor,
        "envelope_batch.sent",
        batch_id,
        document_id=str(document_id),
        version_no=form.version_number,
        rows=len(checked.sendable),
    )
    return _view(session, actor.workspace_id, batch_id)


_BATCH = """
    SELECT b.id, b.department_id, b.document_id, d.name AS document_name, b.file_name,
           b.created_at, b.finished_at, b.total,
           count(*) FILTER (WHERE r.status = 'sent') AS sent,
           count(*) FILTER (WHERE r.status = 'failed') AS failed
    FROM envelope_batches b
    JOIN documents d ON d.id = b.document_id
    LEFT JOIN envelope_batch_rows r ON r.batch_id = b.id
    WHERE b.workspace_id = :w AND {where}
    GROUP BY b.id, d.name
    ORDER BY b.created_at DESC, b.id DESC
"""


def _views(session: Session, workspace_id: uuid.UUID, where: str, **params: Any) -> list[BatchView]:
    rows = session.execute(text(_BATCH.format(where=where)), {"w": workspace_id, **params}).all()
    if not rows:
        return []
    failures: dict[uuid.UUID, list[BatchFailure]] = {row.id: [] for row in rows}
    for failed in session.execute(
        text(
            "SELECT batch_id, row_no, label, error FROM envelope_batch_rows "
            "WHERE batch_id = ANY(:ids) AND status = 'failed' ORDER BY batch_id, row_no"
        ),
        {"ids": list(failures)},
    ):
        failures[failed.batch_id].append(
            BatchFailure(row_no=failed.row_no, label=failed.label, error=failed.error)
        )
    return [
        BatchView(
            id=row.id,
            department_id=row.department_id,
            document_id=row.document_id,
            document_name=row.document_name,
            file_name=row.file_name,
            created_at=row.created_at,
            finished_at=row.finished_at,
            status="finished" if row.finished_at is not None else "sending",
            total=row.total,
            sent=row.sent,
            failed=row.failed,
            failures=failures[row.id],
        )
        for row in rows
    ]


def _view(session: Session, workspace_id: uuid.UUID, batch_id: uuid.UUID) -> BatchView:
    found = _views(session, workspace_id, "b.id = :id", id=batch_id)
    if not found:
        raise NotFound
    return found[0]


def get_batch(session: Session, actor: Actor, batch_id: uuid.UUID) -> BatchView:
    """A batch's progress, for someone who may see its department's sends."""
    view = _view(session, actor.workspace_id, batch_id)
    load_access(session, actor).require(Permission.DOCUMENTS_VIEW_SENDS, view.department_id)
    return view


def recent_batches(session: Session, actor: Actor, department_id: uuid.UUID) -> list[BatchView]:
    """A department's batches still sending or sent in the last day, newest first (FR-8)."""
    get_department(session, actor.workspace_id, department_id)  # 404 for another company's
    load_access(session, actor).require(Permission.DOCUMENTS_VIEW_SENDS, department_id)
    return _views(
        session,
        actor.workspace_id,
        "b.department_id = :dep AND (b.finished_at IS NULL "
        "OR b.created_at > now() - make_interval(secs => :recent))",
        dep=department_id,
        recent=RECENT.total_seconds(),
    )


# --- the job -------------------------------------------------------------------------------------


def _reason(error: DomainError) -> str:
    """Why a row was refused, in the words a single send would have shown."""
    if isinstance(error, ValidationFailed) and error.field_errors:
        return error.field_errors[0].message
    return error.detail or error.title


def _send_next(uow: UnitOfWork, batch_id: uuid.UUID) -> bool:
    """Send the batch's next pending row, in one transaction with the mark on the row, so a row
    is sent exactly once however often the job runs (NFR-3). False when none is left."""
    session = uow.session
    row = session.execute(
        text(
            "SELECT r.row_no, r.request, b.workspace_id, b.document_id, b.created_by "
            "FROM envelope_batch_rows r JOIN envelope_batches b ON b.id = r.batch_id "
            "WHERE r.batch_id = :b AND r.status = 'pending' ORDER BY r.row_no LIMIT 1 "
            "FOR UPDATE OF r"
        ),
        {"b": batch_id},
    ).one_or_none()
    if row is None:
        return False

    def settle(
        status: str, *, envelope_id: uuid.UUID | None = None, error: str | None = None
    ) -> None:
        session.execute(
            text(
                "UPDATE envelope_batch_rows SET status = :s, envelope_id = :e, error = :err, "
                "request = NULL WHERE batch_id = :b AND row_no = :n"
            ),
            {"s": status, "e": envelope_id, "err": error, "b": batch_id, "n": row.row_no},
        )

    # The sender as they are now: their access is checked again for every row (NFR-5).
    actor = actor_of(session, row.workspace_id, row.created_by)
    if actor is None:
        settle("failed", error=NO_ACCESS)
        return True
    try:
        with (
            session.begin_nested()
        ):  # a refused send leaves nothing behind, the row is still marked
            sent = service.send(
                uow,
                actor=actor,
                document_id=row.document_id,
                request=SendRequest.model_validate(row.request),
            )
    except DomainError as refused:
        settle("failed", error=_reason(refused)[:500])
    except DBAPIError:
        raise  # the database itself: nothing about this row; the job is tried again
    except Exception:
        # Anything else is this row's own (a fault its data trips): it is marked and recorded,
        # and the rows after it still go out. Tried again it would fail the same way, and take
        # every later row with it when the job gave up.
        log.exception("envelope_batch.row_failed", batch_id=str(batch_id), row_no=row.row_no)
        settle("failed", error=GAVE_UP)
    else:
        settle("sent", envelope_id=sent.id)
    return True


def _finish(session: Session, batch_id: uuid.UUID) -> None:
    session.execute(
        text(
            "UPDATE envelope_batches SET finished_at = now() WHERE id = :b AND finished_at IS NULL"
        ),
        {"b": batch_id},
    )


def send_batch(context: JobContext) -> None:
    """Send a batch's rows in file order, each in its own transaction (NFR-4). A run that is cut
    short leaves the unsent rows pending for the next attempt."""
    batch_id = uuid.UUID(context.payload["batch_id"])
    while True:
        with context.unit_of_work() as uow:
            if not _send_next(uow, batch_id):
                break
    with context.complete() as uow:
        _finish(uow.session, batch_id)


def give_up(uow: UnitOfWork, payload: dict[str, Any]) -> None:
    """A batch whose job died: its unsent rows are marked so, with nothing of theirs kept, and
    the batch is finished, so it never stays "sending"."""
    batch_id = uuid.UUID(payload["batch_id"])
    uow.session.execute(
        text(
            "UPDATE envelope_batch_rows SET status = 'failed', error = :err, request = NULL "
            "WHERE batch_id = :b AND status = 'pending'"
        ),
        {"err": GAVE_UP, "b": batch_id},
    )
    _finish(uow.session, batch_id)


def register(jobs_registry: JobRegistry) -> list[RecurringJob]:
    jobs_registry.register(
        JobKind(SEND_BATCH, send_batch, max_attempts=MAX_ATTEMPTS, lease=LEASE, on_dead=give_up)
    )
    return []


__all__ = [
    "BatchRequest",
    "BatchView",
    "CheckRequest",
    "authorize",
    "check",
    "create_batch",
    "get_batch",
    "left_out",
    "parse",
    "recent_batches",
    "register",
    "template",
]
