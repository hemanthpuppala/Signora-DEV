"""The signer's API (Phase 8 LLD §1.5): no console sign-in; a signing session cookie instead."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from signora.kernel.db import Database
from signora.modules.signing import service
from signora.modules.signing.sessions import COOKIE
from signora.modules.signing.views import Opened, SignerState

router = APIRouter(prefix="/api/v1/sign", tags=["signing"])


def _db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


class OpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=128)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.post(
    "/open",
    summary="Exchange a signing link's token for this browser's signing session",
    responses={404: {"description": "The link cannot be used (closed, replaced or not genuine)"}},
)
def open_link(body: OpenRequest, request: Request, response: Response) -> Opened:
    with _db(request).unit_of_work() as uow:
        result = service.open_link(uow, body.token, request.cookies.get(COOKIE))
    if result.cookie is not None:
        # Host-only, HTTPS-only, never sent from another site, gone when the browser closes.
        response.set_cookie(
            COOKIE, result.cookie, httponly=True, secure=True, samesite="strict", path="/"
        )
    _no_store(response)
    return result.opened


@router.get(
    "/{recipient_id}",
    summary="Who is signing, what, and their next step",
    responses={
        401: {"description": "No live signing session for this person in this browser"},
        404: {"description": "The request is no longer open"},
    },
)
def signer_state(recipient_id: uuid.UUID, request: Request, response: Response) -> SignerState:
    with _db(request).unit_of_work() as uow:
        who = service.signer(uow, request.cookies.get(COOKIE), recipient_id)
        _no_store(response)
        return service.state(uow, who)
