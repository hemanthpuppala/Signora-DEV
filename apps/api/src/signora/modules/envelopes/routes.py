"""Envelopes' API (Phase 7 LLD §10)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

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


class RecipientChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str | None = Field(default=None, max_length=254)
    name: str | None = Field(default=None, max_length=120)


class SigningLink(BaseModel):
    url: str


class Reminded(BaseModel):
    reminded: int  # how many people were emailed


@router.post(
    "/envelopes/{envelope_id}/remind",
    response_model=Reminded,
    summary="Remind everyone who still has to sign (requires Idempotency-Key)",
)
def remind(
    envelope_id: uuid.UUID,
    request: Request,
    actor: Member,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    with _db(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        count = service.remind(uow, actor=actor, envelope_id=envelope_id)
        return guard.finish(uow, status.HTTP_200_OK, {"reminded": count})


class Resent(BaseModel):
    recipient_id: uuid.UUID


@router.post(
    "/envelopes/{envelope_id}/recipients/{recipient_id}/resend",
    response_model=Resent,
    summary="Email one person their link again, or retry a failed email (requires Idempotency-Key)",
)
def resend(
    envelope_id: uuid.UUID,
    recipient_id: uuid.UUID,
    request: Request,
    actor: Member,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    with _db(request).unit_of_work() as uow:
        if (replay := guard.begin(uow)) is not None:
            return replay
        service.resend(uow, actor=actor, envelope_id=envelope_id, recipient_id=recipient_id)
        return guard.finish(uow, status.HTTP_200_OK, {"recipient_id": str(recipient_id)})


@router.patch(
    "/envelopes/{envelope_id}/recipients/{recipient_id}",
    summary="Correct a person's email (a new link is emailed) or, before they open it, their name",
)
def change_recipient(
    envelope_id: uuid.UUID,
    recipient_id: uuid.UUID,
    body: RecipientChange,
    request: Request,
    actor: Member,
) -> EnvelopeView:
    with _db(request).unit_of_work() as uow:
        service.change_recipient(
            uow,
            actor=actor,
            envelope_id=envelope_id,
            recipient_id=recipient_id,
            email=body.email,
            name=body.name,
        )
        return service.get_envelope(uow.session, actor, envelope_id)


@router.post(
    "/envelopes/{envelope_id}/cancel",
    summary="Withdraw a send: every link stops working (repeat-safe)",
)
def cancel(envelope_id: uuid.UUID, request: Request, actor: Member) -> EnvelopeView:
    with _db(request).unit_of_work() as uow:
        service.cancel(uow, actor=actor, envelope_id=envelope_id)
        return service.get_envelope(uow.session, actor, envelope_id)


@router.get(
    "/envelopes/{envelope_id}/recipients/{recipient_id}/link",
    summary="A person's current signing link (Copy signing link); the copy is audited",
)
def signing_link(
    envelope_id: uuid.UUID, recipient_id: uuid.UUID, request: Request, actor: Member
) -> SigningLink:
    with _db(request).unit_of_work() as uow:
        url = service.signing_link(
            uow, actor=actor, envelope_id=envelope_id, recipient_id=recipient_id
        )
    return SigningLink(url=url)
