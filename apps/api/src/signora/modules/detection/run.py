"""Running detection for one version (Phase 5 LLD §1.2-1.4, §1.7): read, ai, derive, store.

Each stage saves its output in ``detection_runs`` before the next starts, so a retry resumes where
it stopped (a failed AI call never re-reads the document). Every write is guarded by the version,
the run and the expected stage: a run replaced by hand, or taken over by another worker, writes
nothing. ``store`` commits together with the job's guarded completion, so a version is never made
ready by a job that lost its lease. The stage functions take the blob store and the AI as
arguments, so tests run them with their own.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pymupdf
from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.blobstore import BlobStore
from signora.kernel.db import UnitOfWork
from signora.kernel.jobs import JobContext, JsonDict
from signora.kernel.logging import get_logger
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.detection.ai import AiError, Assigner
from signora.modules.detection.derive import Result, check, derive
from signora.modules.detection.prompt import SYSTEM_PROMPT, user_message
from signora.modules.detection.read import read_document
from signora.modules.detection.reading import Reading
from signora.modules.detection.schema import answer_model
from signora.modules.documents import (
    VersionForDetection,
    apply_name_and_description,
    fail_detection,
    finish_detection,
    version_for_detection,
)

log = get_logger("signora.detection")

REPAIR = (
    "Your answer has these problems:\n- {problems}\n"
    "Answer again in full, with every field, fixing them."
)


class StaleRun(Exception):  # noqa: N818 - not an error: the run moved on without this job
    """The run was replaced, finished or taken over: this job stops without writing."""


class Failed(Exception):  # noqa: N818 - a version outcome, not a fault of this code
    """The AI cannot answer and waiting will not change that: the version fails now (§1.1)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _source(store: BlobStore, version: VersionForDetection) -> bytes:
    with store.open(version.source) as handle:
        return handle.read()


def _run_row(session: Session, version_id: uuid.UUID) -> Any:
    return session.execute(
        text("SELECT * FROM detection_runs WHERE version_id = :v"), {"v": version_id}
    ).one_or_none()


def ensure_run(session: Session, version: VersionForDetection) -> uuid.UUID:
    """The run that continues after processing: the unfinished one, or a new one (§1.2)."""
    row = _run_row(session, version.id)
    if row is not None and row.stage != "done":
        return uuid.UUID(str(row.run_id))
    return restart_run(session, version, requested_by=None)


def restart_run(
    session: Session, version: VersionForDetection, *, requested_by: uuid.UUID | None
) -> uuid.UUID:
    """A new run from the start, replacing any earlier one (§1.3)."""
    run_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO detection_runs (version_id, run_id, workspace_id, requested_by) "
            "VALUES (:v, :r, :w, :by) ON CONFLICT (version_id) DO UPDATE SET run_id = :r, "
            "stage = 'read', fields_from = NULL, parsed = NULL, layout = NULL, calls = NULL, "
            "answer = NULL, result = NULL, model = NULL, failure_code = NULL, requested_by = :by, "
            "created_at = now(), finished_at = NULL"
        ),
        {"v": version.id, "r": run_id, "w": version.workspace_id, "by": requested_by},
    )
    return run_id


# Each stage's save: it applies only while this run is still at that stage (§1.7).
_SAVE_READ = text(
    "UPDATE detection_runs SET fields_from = :fields_from, parsed = CAST(:parsed AS jsonb), "
    "layout = :layout, stage = 'ai' WHERE version_id = :v AND run_id = :r AND stage = 'read' "
    "RETURNING version_id"
)
_SAVE_AI = text(
    "UPDATE detection_runs SET calls = CAST(:calls AS jsonb), answer = CAST(:answer AS jsonb), "
    "model = :model, stage = 'derive' WHERE version_id = :v AND run_id = :r AND stage = 'ai' "
    "RETURNING version_id"
)
_SAVE_DERIVE = text(
    "UPDATE detection_runs SET result = CAST(:result AS jsonb), stage = 'store' "
    "WHERE version_id = :v AND run_id = :r AND stage = 'derive' RETURNING version_id"
)
_SAVE_DONE = text(
    "UPDATE detection_runs SET stage = 'done', finished_at = now() "
    "WHERE version_id = :v AND run_id = :r AND stage = 'store' RETURNING version_id"
)
_SAVE_FAILURE = text(
    "UPDATE detection_runs SET failure_code = :code WHERE version_id = :v AND run_id = :r "
    "RETURNING version_id"
)


def _save(
    session: Session, statement: Any, version_id: uuid.UUID, run_id: uuid.UUID, **values: Any
) -> None:
    if session.execute(statement, {**values, "v": version_id, "r": run_id}).one_or_none() is None:
        raise StaleRun(f"run {run_id} moved on")


def run_detection(
    context: JobContext,
    version_id: uuid.UUID,
    *,
    run_id: uuid.UUID | None,
    store: BlobStore,
    assigner: Assigner,
) -> None:
    """Detection for one version, resuming at the saved stage. ``run_id`` is None for the run that
    follows processing (found or created here), set for a run started by hand."""
    with context.unit_of_work() as uow:
        version = version_for_detection(uow.session, version_id)
        if version is not None and version.status == "detecting" and run_id is None:
            run_id = ensure_run(uow.session, version)
    if version is None or version.status != "detecting" or run_id is None:
        with context.complete():  # nothing to do: no longer detecting
            return
    try:
        _stages(context, version, run_id, store=store, assigner=assigner)
    except StaleRun as stale:
        log.info("detection.stale_run", version_id=str(version_id), reason=str(stale))
        with context.complete():
            return
    except Failed as failed:
        with context.complete() as uow:
            try:
                _save(uow.session, _SAVE_FAILURE, version.id, run_id, code=failed.code)
            except StaleRun:
                return
            fail_detection(uow, version, failed.code)


def _row(context: JobContext, version_id: uuid.UUID, run_id: uuid.UUID) -> Any:
    with context.unit_of_work() as uow:
        row = _run_row(uow.session, version_id)
    if row is None or uuid.UUID(str(row.run_id)) != run_id:
        raise StaleRun(f"run {run_id} was replaced")
    return row


def _stages(
    context: JobContext,
    version: VersionForDetection,
    run_id: uuid.UUID,
    *,
    store: BlobStore,
    assigner: Assigner,
) -> None:
    data = _source(store, version)
    row = _row(context, version.id, run_id)
    if row.stage == "read":
        reading = read_document(data)
        with context.unit_of_work() as uow:
            _save(
                uow.session,
                _SAVE_READ,
                version.id,
                run_id,
                fields_from=reading.fields_from,
                parsed=json.dumps(reading.model_dump(mode="json")),
                layout=reading.layout,
            )
        row = _row(context, version.id, run_id)
    if row.stage in ("ai", "derive"):
        reading = Reading.model_validate(row.parsed)
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if row.stage == "ai":
                calls, answer, model_name = _ask(version, reading, document, assigner)
                with context.unit_of_work() as uow:
                    _save(
                        uow.session,
                        _SAVE_AI,
                        version.id,
                        run_id,
                        calls=json.dumps(calls),
                        answer=json.dumps(answer),
                        model=model_name,
                    )
                row = _row(context, version.id, run_id)
            calls = row.calls or []
            result = derive(
                reading,
                row.answer,
                document,
                problems=calls[-1]["problems"] if calls else [],
                repaired=len(calls) > 1,
            )
        with context.unit_of_work() as uow:
            _save(
                uow.session,
                _SAVE_DERIVE,
                version.id,
                run_id,
                result=json.dumps(result.model_dump(mode="json")),
            )
        row = _row(context, version.id, run_id)
    if row.stage == "store":
        _store(context, version, run_id, Result.model_validate(row.result), row)


EMPTY_ANSWER: dict[str, Any] = {
    "roles": [],
    "fields": [],
    "checkbox_groups": [],
    "extra_fields": [],
    "document": None,
}


def _ask(
    version: VersionForDetection, reading: Reading, document: pymupdf.Document, assigner: Assigner
) -> tuple[list[JsonDict], dict[str, Any], str | None]:
    """One call, and one repair call when the checks find problems (§3.4). Nothing to ask: no
    call. A passing failure propagates (the job retries; ``on_dead`` fails it at the end); any
    other fails the version now."""
    if not reading.asked:
        return [], EMPTY_ANSWER, None
    answer_type = answer_model([field.id for field in reading.asked])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": user_message(
                reading,
                current_name=version.document_name,
                instructions=version.ai_instructions,
                write_name_and_description=version.write_name_and_description,
            ),
        },
    ]
    calls: list[JsonDict] = []
    for attempt in (1, 2):
        try:
            call = assigner.assign(messages, answer_type)
        except AiError as error:
            if error.code == "ai_unavailable":
                raise
            raise Failed(error.code) from error
        problems = check(call.answer, reading, document)
        calls.append(
            {
                "request_id": call.request_id,
                "latency_s": call.latency_s,
                "input_tokens": call.usage.input,
                "cached_tokens": call.usage.cached,
                "output_tokens": call.usage.output,
                "reasoning_tokens": call.usage.reasoning,
                "problems": problems,
            }
        )
        if not problems or attempt == 2:
            return calls, call.answer, call.model
        messages = [
            *messages,
            {"role": "assistant", "content": call.content},
            {"role": "user", "content": REPAIR.format(problems="\n- ".join(problems))},
        ]
    raise AssertionError("unreachable: the loop returns on its second attempt")


def _store(
    context: JobContext, version: VersionForDetection, run_id: uuid.UUID, result: Result, row: Any
) -> None:
    """The version's roles, fields and placements, its name and description, and ready (§1.2),
    in the transaction that completes the job."""
    with context.complete() as uow:
        _save(uow.session, _SAVE_DONE, version.id, run_id)
        write_fields(uow.session, version, result)
        if result.document is not None:
            apply_name_and_description(
                uow,
                version,
                name=result.document.name or "",
                description=result.document.description or "",
            )
        finish_detection(uow, version, field_count=len(result.fields))
        _audit(uow, version, result, row)
    log.info(
        "detection.done",
        version_id=str(version.id),
        fields=len(result.fields),
        roles=len(result.roles),
        repaired=result.flags.repaired,
    )


def write_fields(session: Session, version: VersionForDetection, result: Result) -> None:
    """Replace the version's roles, fields and placements with the result's: a constant number of
    statements, O(F + P) rows (§5.4)."""
    params = {"v": version.id}
    session.execute(text("DELETE FROM version_fields WHERE version_id = :v"), params)
    session.execute(text("DELETE FROM version_roles WHERE version_id = :v"), params)
    role_ids: dict[str, uuid.UUID] = {}
    if result.roles:
        rows = session.execute(
            text(
                "INSERT INTO version_roles (workspace_id, version_id, slug, label, kind, position) "
                "SELECT :w, :v, r.slug, r.label, r.kind, r.position FROM jsonb_to_recordset("
                "CAST(:roles AS jsonb)) AS r(slug text, label text, kind text, position int) "
                "RETURNING id, slug"
            ),
            {
                "w": version.workspace_id,
                "v": version.id,
                "roles": json.dumps([role.model_dump() for role in result.roles]),
            },
        ).all()
        role_ids = {row.slug: row.id for row in rows}
    if not result.fields:
        return
    fields = [
        {
            "key": field.key,
            "label": field.label,
            "holds": field.holds,
            "filled_by": field.filled_by,
            "role_id": str(role_ids[field.role]) if field.role in role_ids else None,
            "required": field.required,
            "sensitive": field.sensitive,
            "needs_review": field.needs_review,
        }
        for field in result.fields
    ]
    field_ids = {
        row.key: row.id
        for row in session.execute(
            text(
                "INSERT INTO version_fields (workspace_id, version_id, key, label, holds, "
                "filled_by, role_id, required, sensitive, needs_review, origin) "
                "SELECT :w, :v, f.key, f.label, f.holds, f.filled_by, f.role_id, f.required, "
                "f.sensitive, f.needs_review, 'detected' FROM jsonb_to_recordset(CAST(:fields AS "
                "jsonb)) AS f(key text, label text, holds text, filled_by text, role_id uuid, "
                "required boolean, sensitive boolean, needs_review text) RETURNING id, key"
            ),
            {"w": version.workspace_id, "v": version.id, "fields": json.dumps(fields)},
        )
    }
    dependencies = [
        {
            "id": str(field_ids[f.key]),
            "on_id": str(field_ids[f.depends_on.key]),
            "option": f.depends_on.option,
        }
        for f in result.fields
        if f.depends_on is not None and f.depends_on.key in field_ids
    ]
    if dependencies:
        session.execute(
            text(
                "UPDATE version_fields AS f SET depends_on_field_id = d.on_id, "
                "depends_on_option = d.option FROM jsonb_to_recordset(CAST(:deps AS jsonb)) "
                "AS d(id uuid, on_id uuid, option text) WHERE f.id = d.id"
            ),
            {"deps": json.dumps(dependencies)},
        )
    placements = [
        {
            "field_id": str(field_ids[field.key]),
            "page": placement.page,
            "x0": placement.rect[0],
            "y0": placement.rect[1],
            "x1": placement.rect[2],
            "y1": placement.rect[3],
            "kind": placement.kind,
            "pdf_field": placement.pdf_field,
            "option_value": placement.option_value,
            "option_text": placement.option_text,
        }
        for field in result.fields
        for placement in field.placements
    ]
    session.execute(
        text(
            "INSERT INTO field_placements (workspace_id, version_id, field_id, page, x0, y0, x1, "
            "y1, kind, pdf_field, option_value, option_text) SELECT :w, :v, p.field_id, p.page, "
            "p.x0, p.y0, p.x1, p.y1, p.kind, p.pdf_field, p.option_value, p.option_text FROM "
            "jsonb_to_recordset(CAST(:placements AS jsonb)) AS p(field_id uuid, page int, "
            "x0 float8, y0 float8, x1 float8, y1 float8, kind text, pdf_field text, "
            "option_value text, option_text text)"
        ),
        {"w": version.workspace_id, "v": version.id, "placements": json.dumps(placements)},
    )


def _audit(uow: UnitOfWork, version: VersionForDetection, result: Result, row: Any) -> None:
    calls = row.calls or []
    per_role: dict[str, int] = {}
    for field in result.fields:
        per_role[field.role or field.filled_by] = per_role.get(field.role or field.filled_by, 0) + 1
    record(
        uow,
        chain=AuditChain.workspace(version.workspace_id),
        actor=AuditActor.system(),
        action="document.fields_detected",
        subject=Subject("document", version.document_id),
        data={
            "version_id": str(version.id),
            "fields_from": result.fields_from,
            "fields": len(result.fields),
            "per_role": per_role,
            "needs_review": sum(1 for field in result.fields if field.needs_review),
            "model": row.model,
            "calls": len(calls),
            "input_tokens": sum(call["input_tokens"] for call in calls),
            "output_tokens": sum(call["output_tokens"] for call in calls),
            "repaired": result.flags.repaired,
            "addressed_to_ai": result.flags.addressed_to_ai,
        },
    )


def settle_dead_run(uow: UnitOfWork, payload: JsonDict) -> None:
    """The job died (backbone §1.4 on_dead): the version fails with its stage's code, so it never
    stays "Finding fields" (§1.2): the AI stage as unavailable, any other as our failure."""
    version = version_for_detection(uow.session, uuid.UUID(payload["version_id"]))
    if version is None:
        return
    row = _run_row(uow.session, version.id)
    code = "ai_unavailable" if row is not None and row.stage == "ai" else "detection_failed"
    if row is not None:
        uow.session.execute(
            text("UPDATE detection_runs SET failure_code = :c WHERE version_id = :v"),
            {"c": code, "v": version.id},
        )
    fail_detection(uow, version, code)
