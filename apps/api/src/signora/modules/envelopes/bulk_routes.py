"""A bulk send's API (Bulk send LLD §8)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import anyio
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from signora.kernel.db import Database
from signora.kernel.errors import RateLimited
from signora.kernel.idempotency import IdempotencyGuard, idempotency_guard
from signora.kernel.ratelimit import RateLimiter
from signora.kernel.spool import spool_body
from signora.modules.envelopes import bulk
from signora.modules.envelopes.bulk_files import MAX_FILE_BYTES, XLSX_TYPE
from signora.modules.envelopes.bulk_sheet import Sheet
from signora.modules.identity_access import Actor, current_actor

router = APIRouter(prefix="/api/v1", tags=["bulk send"])
Member = Annotated[Actor, Depends(current_actor)]

_VERSION = "/documents/{document_id}/versions/{version_id}"
_RAW_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}
_FILE: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/octet-stream": {}}, "description": "The file"}
}


# How often one person may do each, an hour: generous for real work (a sender re-checks on every
# corrected cell), a ceiling on work a signed-in person could otherwise ask for without end.
WINDOW = timedelta(hours=1)
FILES_PER_HOUR = 60
CHECKS_PER_HOUR = 1500
BATCHES_PER_HOUR = 30


def _limit(request: Request, actor: Actor, what: str, limit: int) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    retry = limiter.hit(f"envelopes.bulk.{what}:{actor.user_id}", limit=limit, window=WINDOW)
    if retry is not None:
        raise RateLimited(retry)


def _db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def _download(data: bytes, filename: str, media_type: str) -> Response:
    """A file to save, named for people: the name survives any characters in a template's name."""
    # A header is one line: nothing in a template's name may end it or start another.
    name = "".join(ch for ch in filename if ch.isprintable()) or "download"
    plain = name.encode("ascii", "replace").decode().replace('"', "'").replace("\\", "_")
    disposition = f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"
    return Response(data, media_type=media_type, headers={"Content-Disposition": disposition})


@router.get(
    f"{_VERSION}/bulk-template",
    summary="The spreadsheet to fill in for a bulk send of this version (XLSX)",
    response_class=Response,
    responses={**_FILE, 409: {"description": "Not approved, or nobody signs it"}},
)
def bulk_template(
    document_id: uuid.UUID, version_id: uuid.UUID, request: Request, actor: Member
) -> Response:
    with _db(request).unit_of_work() as uow:
        filename, data = bulk.template(uow.session, actor, document_id, version_id)
    return _download(data, filename, XLSX_TYPE)


@router.post(
    f"{_VERSION}/bulk-rows",
    summary="Read a filled spreadsheet (XLSX or CSV, the raw bytes as the body): rows and problems",
    openapi_extra=_RAW_BODY,
    responses={
        409: {"description": "Not approved, or made for another version"},
        413: {"description": "Over 5 MB"},
        422: {"description": "Not a spreadsheet, empty, or over 1,000 rows"},
    },
)
async def read_bulk_rows(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    actor: Member,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
) -> Sheet:
    database = _db(request)

    def authorize() -> None:
        with database.unit_of_work() as uow:
            bulk.authorize(uow.session, actor, document_id, version_id)

    await run_in_threadpool(authorize)  # before reading the body
    _limit(request, actor, "file", FILES_PER_HOUR)
    path: Path = await spool_body(request, max_bytes=MAX_FILE_BYTES)

    def parse() -> Sheet:
        with database.unit_of_work() as uow:
            return bulk.parse(
                uow.session,
                actor,
                document_id,
                version_id,
                filename=filename,
                data=path.read_bytes(),
            )

    try:
        return await run_in_threadpool(parse)
    finally:
        await anyio.Path(path).unlink(missing_ok=True)


@router.post(
    f"{_VERSION}/bulk-rows/check",
    summary="Check rows again after edits: the same sheet with each row's problems",
)
def check_bulk_rows(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    body: bulk.CheckRequest,
    request: Request,
    actor: Member,
) -> Sheet:
    _limit(request, actor, "check", CHECKS_PER_HOUR)
    with _db(request).unit_of_work() as uow:
        return bulk.check(uow.session, actor, document_id, version_id, body)


@router.post(
    f"{_VERSION}/bulk-rows/left-out",
    summary="The given rows as a CSV with the spreadsheet's headers",
    response_class=Response,
    responses=_FILE,
)
def left_out_rows(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    body: bulk.CheckRequest,
    request: Request,
    actor: Member,
) -> Response:
    with _db(request).unit_of_work() as uow:
        data = bulk.left_out(uow.session, actor, document_id, version_id, body)
    return _download(data, "Rows left out.csv", "text/csv; charset=utf-8")


@router.post(
    "/documents/{document_id}/envelope-batches",
    status_code=status.HTTP_201_CREATED,
    response_model=bulk.BatchView,
    summary="Send a checked sheet: one envelope per row, in the background (requires "
    "Idempotency-Key)",
    responses={
        409: {"description": "Not approved or archived"},
        422: {"description": "A row still has a problem; nothing is sent"},
    },
)
def send_batch(
    document_id: uuid.UUID,
    body: bulk.BatchRequest,
    request: Request,
    actor: Member,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    with _db(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        _limit(request, actor, "batch", BATCHES_PER_HOUR)
        batch = bulk.create_batch(uow, actor=actor, document_id=document_id, request=body)
        return guard.finish(uow, status.HTTP_201_CREATED, batch.model_dump(mode="json"))


@router.get("/envelope-batches/{batch_id}", summary="A bulk send's progress and its failed rows")
def get_batch(batch_id: uuid.UUID, request: Request, actor: Member) -> bulk.BatchView:
    with _db(request).unit_of_work() as uow:
        return bulk.get_batch(uow.session, actor, batch_id)


class Batches(BaseModel):
    batches: list[bulk.BatchView]


@router.get(
    "/departments/{department_id}/envelope-batches",
    summary="A department's bulk sends still going, or sent in the last day",
)
def list_batches(department_id: uuid.UUID, request: Request, actor: Member) -> Batches:
    with _db(request).unit_of_work() as uow:
        return Batches(batches=bulk.recent_batches(uow.session, actor, department_id))
