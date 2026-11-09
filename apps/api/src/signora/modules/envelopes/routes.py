"""Envelopes' API (Phase 7 LLD §10)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from signora.kernel.db import Database
from signora.kernel.idempotency import IdempotencyGuard, idempotency_guard
from signora.modules.envelopes import service
from signora.modules.envelopes.form import SendForm
from signora.modules.envelopes.sending import SendRequest
from signora.modules.envelopes.views import EnvelopeView
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


@router.post(
    "/documents/{document_id}/envelopes",
    status_code=status.HTTP_201_CREATED,
    response_model=EnvelopeView,
    summary="Send an approved version to its parties (requires Idempotency-Key)",
    responses={409: {"description": "Not approved, archived, or one person on two parties"}},
)
def send_envelope(
    document_id: uuid.UUID,
    body: SendRequest,
    request: Request,
    actor: Member,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    with _db(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        sent = service.send(uow, actor=actor, document_id=document_id, request=body)
        return guard.finish(uow, status.HTTP_201_CREATED, sent.model_dump(mode="json"))


@router.get("/envelopes/{envelope_id}", summary="One envelope: recipients, values, timeline")
def get_envelope(envelope_id: uuid.UUID, request: Request, actor: Member) -> EnvelopeView:
    with _db(request).unit_of_work() as uow:
        return service.get_envelope(uow.session, actor, envelope_id)
