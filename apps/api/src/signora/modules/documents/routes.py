"""Document endpoints (Phase 4 LLD). Handlers are plain ``def`` except the streaming upload."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from signora.kernel.blobstore import BlobRef, BlobStore
from signora.kernel.config import Settings
from signora.kernel.db import Database
from signora.kernel.errors import RateLimited
from signora.kernel.idempotency import IdempotencyGuard, idempotency_guard
from signora.kernel.ratelimit import RateLimiter
from signora.kernel.spool import spool_body
from signora.modules.departments import load_access
from signora.modules.documents import service, uploads
from signora.modules.documents.domain import (
    AI_INSTRUCTIONS_MAX,
    DESCRIPTION_MAX,
    failure_message,
    name_from_filename,
    scanned_message,
)
from signora.modules.documents.errors import VersionNotReady
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


class DuplicateView(BaseModel):
    """The same bytes already in the department (§2.3): the screen asks before going on."""

    document_id: uuid.UUID
    document_name: str
    version_number: int
    archived: bool


class UploadView(BaseModel):
    id: uuid.UUID
    filename: str
    kind: Literal["pdf", "docx"]
    bytes: int
    suggested_name: str  # the file name without its extension (§2.4)
    expires_at: datetime
    duplicate: DuplicateView | None


def upload_view(row: uploads.Upload, duplicate: service.Duplicate | None) -> UploadView:
    return UploadView(
        id=row.id,
        filename=row.filename,
        kind=row.kind,
        bytes=row.bytes,
        suggested_name=name_from_filename(row.filename),
        expires_at=row.expires_at,
        duplicate=None
        if duplicate is None
        else DuplicateView(
            document_id=duplicate.document_id,
            document_name=duplicate.document_name,
            version_number=duplicate.version_no,
            archived=duplicate.archived,
        ),
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

    def store() -> UploadView:
        with database.unit_of_work() as uow:
            row = uploads.store_upload(
                uow,
                actor=actor,
                department_id=department_id,
                filename=filename,
                path=path,
                store=_store(request),
                max_bytes=settings.max_bytes,
            )
            duplicate = service.find_duplicate(
                uow.session, actor.workspace_id, department_id, row.sha256
            )
            return upload_view(row, duplicate)

    try:
        return await run_in_threadpool(store)
    finally:
        await anyio.Path(path).unlink(missing_ok=True)


# --- documents and versions ----------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PersonRef(BaseModel):
    id: uuid.UUID
    name: str


class VersionRef(BaseModel):
    id: uuid.UUID
    number: int


class LatestVersion(VersionRef):
    status: Literal["processing", "needs_password", "needs_ocr", "failed", "processed"]
    created_at: datetime


class DocumentSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    kind: Literal["pdf", "docx"] | None  # of the current version
    page_count: int | None  # of the current version
    current_version: VersionRef | None  # none until the first version is ready (topic 4)
    latest_version: LatestVersion  # the newest upload and its state
    updated_at: datetime
    archived_at: datetime | None


class Problem(BaseModel):
    """Why a version is not ready, in words a person acts on (§2.5, §3.2-3.4)."""

    code: str
    message: str
    can_retry: bool


class PageView(BaseModel):
    """A page as displayed (rotation applied), in PDF points: the viewer lays pages out from these
    before the file loads, and Phase 6 places fields in the same units."""

    width: float
    height: float
    rotation: int


class VersionView(BaseModel):
    id: uuid.UUID
    number: int
    status: Literal["processing", "needs_password", "needs_ocr", "failed", "processed"]
    problem: Problem | None
    kind: Literal["pdf", "docx"]
    filename: str
    bytes: int
    page_count: int | None
    pages: list[PageView]  # empty until processed
    pages_without_text: list[int]
    ai_instructions: str
    uploaded_by: PersonRef
    created_at: datetime
    processed_at: datetime | None
    is_current: bool


class DocumentDetail(DocumentSummary):
    department_id: uuid.UUID
    require_email_code: bool
    created_by: PersonRef
    created_at: datetime
    access: Literal["edit", "read"]  # the caller's, in this document's department
    versions: list[VersionView]  # newest first


def summary(row: service.DocumentRow) -> DocumentSummary:
    return DocumentSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        kind=row.current_kind,
        page_count=row.current_page_count,
        current_version=None
        if row.current_version_id is None or row.current_version_no is None
        else VersionRef(id=row.current_version_id, number=row.current_version_no),
        latest_version=LatestVersion(
            id=row.latest_version_id,
            number=row.latest_version_no,
            status=row.latest_status,  # type: ignore[arg-type]  # the database checks the values
            created_at=row.latest_created_at,
        ),
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def _problem(version: service.VersionRow, max_pages: int) -> Problem | None:
    if version.status == "failed" and version.failure_code is not None:
        message = failure_message(
            version.failure_code, pages=version.page_count, max_pages=max_pages
        )
        return Problem(
            code=version.failure_code, message=message, can_retry=version.failure_temporary
        )
    if version.status == "needs_ocr":
        return Problem(
            code="needs_ocr",
            message=scanned_message(version.pages_without_text),
            can_retry=False,
        )
    if version.status == "needs_password":
        return Problem(
            code="needs_password",
            message="This PDF needs a password to open",
            can_retry=False,
        )
    return None


def version_view(
    version: service.VersionRow, current_id: uuid.UUID | None, max_pages: int
) -> VersionView:
    return VersionView(
        id=version.id,
        number=version.version_no,
        status=version.status,  # type: ignore[arg-type]  # the database checks the values
        problem=_problem(version, max_pages),
        kind=version.source_kind,
        filename=version.source_filename,
        bytes=version.source_bytes,
        page_count=version.page_count,
        pages=[PageView(**page) for page in version.pages or []],
        pages_without_text=version.pages_without_text,
        ai_instructions=version.ai_instructions,
        uploaded_by=PersonRef(id=version.uploaded_by_id, name=version.uploaded_by_name),
        created_at=version.created_at,
        processed_at=version.processed_at,
        is_current=version.id == current_id,
    )


def detail(
    request: Request, session: Session, actor: Actor, row: service.DocumentRow
) -> DocumentDetail:
    versions = service.list_versions(session, actor.workspace_id, row.id)
    rights = load_access(session, actor)
    max_pages = _settings(request).documents.max_pages
    return DocumentDetail(
        **summary(row).model_dump(),
        department_id=row.department_id,
        require_email_code=row.require_email_code,
        created_by=PersonRef(id=row.created_by_id, name=row.created_by_name),
        created_at=row.created_at,
        access=rights.level(row.department_id),
        versions=[version_view(v, row.current_version_id, max_pages) for v in versions],
    )


NameInput = Annotated[str, Field(max_length=500)]


class CreateDocument(_Body):
    name: NameInput
    ai_instructions: Annotated[str, Field(max_length=AI_INSTRUCTIONS_MAX * 2)] = ""
    upload_id: uuid.UUID
    allow_duplicate: bool = False  # the person chose "Upload anyway as a separate document"


class AddVersion(_Body):
    ai_instructions: Annotated[str, Field(max_length=AI_INSTRUCTIONS_MAX * 2)] = ""
    upload_id: uuid.UUID


class UpdateDocument(_Body):
    name: NameInput | None = None
    description: Annotated[str, Field(max_length=DESCRIPTION_MAX * 2)] | None = None
    require_email_code: bool | None = None


@router.get("/departments/{department_id}/documents", summary="Documents of a department")
def list_documents(
    department_id: uuid.UUID,
    request: Request,
    actor: Member,
    status_filter: Annotated[Literal["active", "archived"], Query(alias="status")] = "active",
) -> list[DocumentSummary]:
    with _db(request).unit_of_work() as uow:
        rows = service.list_documents(
            uow.session, actor.workspace_id, department_id, archived=status_filter == "archived"
        )
    return [summary(row) for row in rows]


@router.post(
    "/departments/{department_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentDetail,
    summary="Create a document from an upload (requires Idempotency-Key)",
)
def create_document(
    department_id: uuid.UUID,
    body: CreateDocument,
    request: Request,
    actor: Member,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    with _db(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        row, _ = service.create_document(
            uow,
            actor=actor,
            department_id=department_id,
            name=body.name,
            ai_instructions=body.ai_instructions,
            upload_id=body.upload_id,
            allow_duplicate=body.allow_duplicate,
        )
        created = detail(request, uow.session, actor, row).model_dump(mode="json")
        return guard.finish(uow, status.HTTP_201_CREATED, created)


@router.get("/documents/{document_id}", summary="One document with its versions")
def get_document(document_id: uuid.UUID, request: Request, actor: Member) -> DocumentDetail:
    with _db(request).unit_of_work() as uow:
        row = service.get_document(uow.session, actor.workspace_id, document_id)
        return detail(request, uow.session, actor, row)


@router.patch("/documents/{document_id}", summary="Rename, describe, or set the email code")
def update_document(
    document_id: uuid.UUID, body: UpdateDocument, request: Request, actor: Member
) -> DocumentDetail:
    with _db(request).unit_of_work() as uow:
        row = service.update_document(
            uow,
            actor=actor,
            document_id=document_id,
            name=body.name,
            description=body.description,
            require_email_code=body.require_email_code,
        )
        return detail(request, uow.session, actor, row)


@router.post("/documents/{document_id}/archive", summary="Archive a document (repeat-safe)")
def archive_document(document_id: uuid.UUID, request: Request, actor: Member) -> DocumentDetail:
    with _db(request).unit_of_work() as uow:
        row = service.archive_document(uow, actor=actor, document_id=document_id)
        return detail(request, uow.session, actor, row)


@router.post("/documents/{document_id}/restore", summary="Restore an archived document")
def restore_document(document_id: uuid.UUID, request: Request, actor: Member) -> DocumentDetail:
    with _db(request).unit_of_work() as uow:
        row = service.restore_document(uow, actor=actor, document_id=document_id)
        return detail(request, uow.session, actor, row)


@router.post(
    "/documents/{document_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentDetail,
    summary="Add a version from an upload (requires Idempotency-Key)",
)
def add_version(
    document_id: uuid.UUID,
    body: AddVersion,
    request: Request,
    actor: Member,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    with _db(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        service.add_version(
            uow,
            actor=actor,
            document_id=document_id,
            ai_instructions=body.ai_instructions,
            upload_id=body.upload_id,
        )
        row = service.get_document(uow.session, actor.workspace_id, document_id)
        created = detail(request, uow.session, actor, row).model_dump(mode="json")
        return guard.finish(uow, status.HTTP_201_CREATED, created)


class UnlockVersion(_Body):
    password: Annotated[str, Field(min_length=1, max_length=1024)]


@router.post(
    "/documents/{document_id}/versions/{version_id}/retry",
    summary="Try processing again after a passing failure (repeat-safe)",
)
def retry_version(
    document_id: uuid.UUID, version_id: uuid.UUID, request: Request, actor: Member
) -> DocumentDetail:
    with _db(request).unit_of_work() as uow:
        service.retry_version(uow, actor=actor, document_id=document_id, version_id=version_id)
        row = service.get_document(uow.session, actor.workspace_id, document_id)
        return detail(request, uow.session, actor, row)


@router.post(
    "/documents/{document_id}/versions/{version_id}/unlock",
    summary="Open a password-protected PDF with its password (never stored)",
)
def unlock_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    body: UnlockVersion,
    request: Request,
    actor: Member,
) -> DocumentDetail:
    limiter: RateLimiter = request.app.state.rate_limiter
    with _db(request).unit_of_work() as uow:
        service.unlock_version(
            uow,
            actor=actor,
            document_id=document_id,
            version_id=version_id,
            password=body.password,
            store=_store(request),
            limiter=limiter,
        )
        row = service.get_document(uow.session, actor.workspace_id, document_id)
        return detail(request, uow.session, actor, row)


class MakeCurrent(_Body):
    version_id: uuid.UUID


@router.post(
    "/documents/{document_id}/current-version",
    summary="Make a ready version the one new sends use (repeat-safe)",
)
def make_current(
    document_id: uuid.UUID, body: MakeCurrent, request: Request, actor: Member
) -> DocumentDetail:
    with _db(request).unit_of_work() as uow:
        service.make_current(uow, actor=actor, document_id=document_id, version_id=body.version_id)
        row = service.get_document(uow.session, actor.workspace_id, document_id)
        return detail(request, uow.session, actor, row)


# --- files ---------------------------------------------------------------------------------

_DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_NO_STORE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _served_version(
    request: Request, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[service.DocumentRow, service.VersionRow]:
    with _db(request).unit_of_work() as uow:
        document = service.get_document(uow.session, actor.workspace_id, document_id)
        version = service.get_version(uow.session, actor.workspace_id, document_id, version_id)
    return document, version


@router.get(
    "/documents/{document_id}/versions/{version_id}/pdf",
    summary="The version's working copy, for the viewer (supports HTTP ranges)",
    response_class=FileResponse,
)
def version_pdf(
    document_id: uuid.UUID, version_id: uuid.UUID, request: Request, actor: Member
) -> FileResponse:
    """Only the cleaned working copy is ever shown in the page (topic 5 §5.2)."""
    document, version = _served_version(request, actor, document_id, version_id)
    if version.pdf_sha256 is None or version.pdf_bytes is None:
        raise VersionNotReady("This version isn't ready to view yet")
    ref = BlobRef(actor.workspace_id, version.pdf_sha256, version.pdf_bytes)
    return FileResponse(
        _store(request).path(ref),
        media_type="application/pdf",
        filename=f"{document.name} v{version.version_no}.pdf",
        content_disposition_type="inline",
        headers=_NO_STORE,
    )


@router.get(
    "/documents/{document_id}/versions/{version_id}/original",
    summary="The file exactly as uploaded, as a download",
    response_class=FileResponse,
)
def version_original(
    document_id: uuid.UUID, version_id: uuid.UUID, request: Request, actor: Member
) -> FileResponse:
    """Always an attachment, never shown in the page: it may still hold scripts (§5.2)."""
    _, version = _served_version(request, actor, document_id, version_id)
    ref = BlobRef(actor.workspace_id, version.source_sha256, version.source_bytes)
    return FileResponse(
        _store(request).path(ref),
        media_type="application/pdf" if version.source_kind == "pdf" else _DOCX_TYPE,
        filename=version.source_filename,
        content_disposition_type="attachment",
        headers=_NO_STORE,
    )
