"""Review's API (Phase 6 LLD §10): saving a version's fields."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from signora.kernel.db import Database
from signora.modules.identity_access import Actor, current_actor
from signora.modules.review import service
from signora.modules.review.fieldset import FieldSet, Saved

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
