"""Review's API (Phase 6 LLD §10): saving a version's fields, in place or as the next version, and
approving it."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from signora.kernel.db import Database
from signora.kernel.idempotency import IdempotencyGuard, idempotency_guard
from signora.modules.identity_access import Actor, current_actor
from signora.modules.review import service
from signora.modules.review.fieldset import Approval, FieldSet, Revised, Saved

router = APIRouter(prefix="/api/v1", tags=["review"])
Member = Annotated[Actor, Depends(current_actor)]


def _db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


@router.put(
    "/documents/{document_id}/versions/{version_id}/fields",
    summary="Save a version's parties, fields and places as the editor holds them",
    responses={409: {"description": "Changed by someone else, approved, or not in review"}},
)
def save_fields(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    fieldset: FieldSet,
    request: Request,
    actor: Member,
) -> Saved:
    with _db(request).unit_of_work() as uow:
        revision = service.save(
            uow, actor=actor, document_id=document_id, version_id=version_id, fieldset=fieldset
        )
    return Saved(revision=revision)


@router.post(
    "/documents/{document_id}/versions/{version_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve a version in review: its fields freeze, and the newest approved is current",
    responses={
        409: {"description": "Changed since it was opened, warnings changed, or not in review"}
    },
)
def approve(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    approval: Approval,
    request: Request,
    actor: Member,
) -> None:
    with _db(request).unit_of_work() as uow:
        service.approve(
            uow, actor=actor, document_id=document_id, version_id=version_id, approval=approval
        )


@router.post(
    "/documents/{document_id}/versions/{version_id}/revisions",
    status_code=status.HTTP_201_CREATED,
    response_model=Revised,
    summary="Save an edit of an approved version as the next version (requires Idempotency-Key)",
    responses={409: {"description": "Not approved, or changed since it was opened"}},
)
def revise_fields(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    fieldset: FieldSet,
    request: Request,
    actor: Member,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    with _db(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        revised = service.revise(
            uow, actor=actor, document_id=document_id, source_id=version_id, fieldset=fieldset
        )
        return guard.finish(uow, status.HTTP_201_CREATED, revised.model_dump(mode="json"))
