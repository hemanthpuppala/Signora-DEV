"""Envelopes' API (Phase 7 LLD §10)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from signora.kernel.db import Database
from signora.modules.envelopes import service
from signora.modules.envelopes.form import SendForm
from signora.modules.identity_access import Actor, current_actor

router = APIRouter(prefix="/api/v1", tags=["envelopes"])
Member = Annotated[Actor, Depends(current_actor)]


def _db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


@router.get(
    "/documents/{document_id}/versions/{version_id}/send-form",
    summary="What sending an approved version asks: details, signers, countersigners, settings",
    responses={409: {"description": "The version is not approved"}},
)
def send_form(
    document_id: uuid.UUID, version_id: uuid.UUID, request: Request, actor: Member
) -> SendForm:
    with _db(request).unit_of_work() as uow:
        return service.send_form(uow.session, actor, document_id, version_id)
