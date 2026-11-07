"""FastAPI integration for idempotent create endpoints (backbone LLD §3.2-3.4).

Usage in a module router::

    @router.post("/projects", status_code=201)
    def create_project(
        body: NewProject, guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)]
    ):
        with database.unit_of_work() as uow:
            if (replay := guard.begin(uow)) is not None:
                return replay
            project = projects.create(uow, body)
            return guard.finish(uow, 201, project.model_dump(mode="json"))
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from signora.kernel.db import UnitOfWork
from signora.kernel.errors import IdempotencyKeyMissing
from signora.kernel.idempotency.core import begin, fingerprint, finish, validate_key

HEADER = "Idempotency-Key"
_CHUNK = 1024 * 1024


async def _file_sha256(upload: UploadFile) -> str:
    digest = hashlib.sha256()
    while chunk := await upload.read(_CHUNK):
        digest.update(chunk)
    await upload.seek(0)  # the endpoint reads the file again
    return digest.hexdigest()


async def request_fingerprint(request: Request) -> bytes:
    """SHA-256 of the parsed request, independent of transport details (LLD §3.3).

    JSON: canonical JSON. Multipart/urlencoded: sorted (field, value) pairs with files replaced by
    the SHA-256 of their bytes, so a retry with a new multipart boundary has the same fingerprint.
    """
    content_type = request.headers.get("content-type", "")
    if content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        form = await request.form()
        items: list[list[str]] = []
        for name, value in form.multi_items():
            if isinstance(value, UploadFile):
                items.append(["file", name, await _file_sha256(value)])
            else:
                items.append(["field", name, value])
        return fingerprint(sorted(items))
    raw = await request.body()
    if not raw:
        return hashlib.sha256(b"").digest()
    try:
        return fingerprint(await request.json())
    except ValueError:  # not JSON; validation will reject it, but fingerprint the bytes
        return hashlib.sha256(raw).digest()


@dataclass(frozen=True)
class IdempotencyGuard:
    scope: str
    key: str
    request_hash: bytes

    def begin(self, uow: UnitOfWork) -> JSONResponse | None:
        """Reserve the key; returns the stored response to replay, or None to run the action."""
        stored = begin(uow.session, self.scope, self.key, self.request_hash)
        if stored is None:
            return None
        return JSONResponse(stored.body, status_code=stored.status)

    def finish(self, uow: UnitOfWork, status: int, body: Any) -> JSONResponse:
        """Store the response with the key (same transaction) and return it."""
        finish(uow.session, self.scope, self.key, status, body)
        return JSONResponse(body, status_code=status)


async def idempotency_guard(request: Request) -> IdempotencyGuard:
    """Dependency for create endpoints: the key is required (400 when missing or malformed)."""
    key = request.headers.get(HEADER)
    if key is None:
        raise IdempotencyKeyMissing
    # Scope = acting user + method + concrete path. Until accounts exist (Phase 2) the actor is
    # "anonymous"; authentication will set request.state.actor_id.
    actor = getattr(request.state, "actor_id", None) or "anonymous"
    return IdempotencyGuard(
        scope=f"{actor}:{request.method} {request.url.path}",
        key=validate_key(key),
        request_hash=await request_fingerprint(request),
    )
