"""Document endpoints (Phase 4 LLD). Handlers are plain ``def`` except the streaming upload."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from signora.kernel.blobstore import BlobStore
from signora.kernel.config import Settings
from signora.kernel.db import Database
from signora.kernel.errors import RateLimited
from signora.kernel.ratelimit import RateLimiter
from signora.kernel.spool import spool_body
from signora.modules.documents import uploads
from signora.modules.documents.domain import name_from_filename
from signora.modules.identity_access import Actor, current_actor

router = APIRouter(prefix="/api/v1", tags=["documents"])

Member = Annotated[Actor, Depends(current_actor)]
UPLOAD_WINDOW = timedelta(hours=1)


def _db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _store(request: Request) -> BlobStore:
    store: BlobStore = request.app.state.blob_store
    return store


class UploadView(BaseModel):
    id: uuid.UUID
    filename: str
    kind: Literal["pdf", "docx"]
    bytes: int
    suggested_name: str  # the file name without its extension (§2.4)
    expires_at: datetime


def upload_view(row: uploads.Upload) -> UploadView:
    return UploadView(
        id=row.id,
        filename=row.filename,
        kind=row.kind,
        bytes=row.bytes,
        suggested_name=name_from_filename(row.filename),
        expires_at=row.expires_at,
    )


_RAW_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


@router.post(
    "/departments/{department_id}/uploads",
    status_code=status.HTTP_201_CREATED,
    summary="Upload one PDF or .docx file (the raw bytes as the body)",
    openapi_extra=_RAW_BODY,
)
async def create_upload(
    department_id: uuid.UUID,
    request: Request,
    actor: Member,
    filename: Annotated[str, Query(min_length=1, max_length=1000)],
) -> UploadView:
    """Streams the body to disk (never into memory) and refuses it past the size limit. A retry
    stores the same bytes under the same hash, so no ``Idempotency-Key`` is needed."""
    database, settings = _db(request), _settings(request).documents

    def authorize() -> None:
        with database.unit_of_work() as uow:
            uploads.authorize_upload(uow.session, actor, department_id)

    await run_in_threadpool(authorize)  # before reading 50 MB
    limiter: RateLimiter = request.app.state.rate_limiter
    retry = limiter.hit(
        f"documents.upload:{actor.user_id}", limit=settings.uploads_per_hour, window=UPLOAD_WINDOW
    )
    if retry is not None:
        raise RateLimited(retry)
    path = await spool_body(request, max_bytes=settings.max_bytes)

    def store() -> uploads.Upload:
        with database.unit_of_work() as uow:
            return uploads.store_upload(
                uow,
                actor=actor,
                department_id=department_id,
                filename=filename,
                path=path,
                store=_store(request),
                max_bytes=settings.max_bytes,
            )

    try:
        return upload_view(await run_in_threadpool(store))
    finally:
        await anyio.Path(path).unlink(missing_ok=True)
