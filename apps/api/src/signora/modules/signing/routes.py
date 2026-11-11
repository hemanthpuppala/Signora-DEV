"""The signer's API (Phase 8 LLD §1.5): no console sign-in; a signing session cookie instead."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from signora.kernel.blobstore import BlobStore
from signora.kernel.db import Database
from signora.kernel.errors import FieldError, ValidationFailed
from signora.kernel.http import attachment
from signora.kernel.idempotency import IdempotencyGuard, idempotency_guard
from signora.modules.envelopes import DownloadPart, read_completed
from signora.modules.signing import decline, drafts, drawing, limits, service, signatures, submit
from signora.modules.signing.document import SignerDocument
from signora.modules.signing.errors import LinkClosed, VerifyFirst
from signora.modules.signing.sessions import COOKIE
from signora.modules.signing.views import CodeSentView, DoneView, Opened, SignerState
from signora.modules.typesetting import FontView

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
    limits.by_address(request, "open")
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
        who = service.acting(uow, request, recipient_id)
        _no_store(response)
        return service.state(uow, who)


class CodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    again: bool = False


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[0-9]{6}$")


@router.post(
    "/{recipient_id}/code",
    summary="Email this person a code, or keep the live one",
    responses={
        409: {"description": "This envelope asks for no code"},
        429: {"description": "Too soon after the last code, or too many codes this hour"},
    },
)
def send_code(
    recipient_id: uuid.UUID, body: CodeRequest, request: Request, response: Response
) -> CodeSentView:
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        sent = service.send_code(uow, who, again=body.again)
    _no_store(response)
    return CodeSentView(
        sent_at=sent.sent_at, email_masked=sent.email_masked, resend_after=sent.resend_after
    )


@router.post(
    "/{recipient_id}/verify",
    summary="Check the email code; on a match this browser may go on for this person",
    responses={
        410: {"description": "The code expired, was used, or had too many wrong tries"},
        422: {"description": "A wrong code (how many tries are left is in the message)"},
    },
)
def verify(
    recipient_id: uuid.UUID, body: VerifyRequest, request: Request, response: Response
) -> Opened:
    limits.by_address(request, "verify")
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        opened = service.verify(uow, who, body.code)
    _no_store(response)
    return opened


class ConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disclosure_version: str = Field(min_length=1, max_length=40)


@router.post(
    "/{recipient_id}/consent",
    summary="Agree to use electronic records and signatures (once per person)",
    responses={
        403: {"description": "The email code comes first"},
        409: {"description": "The disclosure changed: read it again"},
    },
)
def consent(
    recipient_id: uuid.UUID, body: ConsentRequest, request: Request, response: Response
) -> Opened:
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        opened = service.give_consent(uow, who, body.disclosure_version)
    _no_store(response)
    return opened


_DOCUMENT: dict[int | str, dict[str, Any]] = {
    401: {"description": "No live signing session for this person in this browser"},
    403: {"description": "The code or consent comes first"},
    404: {"description": "The request is no longer open"},
}


@router.get(
    "/{recipient_id}/document",
    summary="The document's fields as this person sees them",
    responses=_DOCUMENT,
)
def document(recipient_id: uuid.UUID, request: Request, response: Response) -> SignerDocument:
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        view = service.document(uow, who)
    _no_store(response)
    return view


@router.get(
    "/{recipient_id}/pdf",
    summary="The document's pages (values are drawn over them, never in them)",
    response_class=FileResponse,
    responses=_DOCUMENT,
)
def pdf(recipient_id: uuid.UUID, request: Request) -> FileResponse:
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        version = service.version_of(uow, who)
    store: BlobStore = request.app.state.blob_store
    return FileResponse(
        store.path(version.pdf),
        media_type="application/pdf",
        filename=f"{version.document_name}.pdf",
        content_disposition_type="inline",
        headers={"Cache-Control": "no-store"},
    )


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(max_length=2000)


class DraftSaved(BaseModel):
    value: str  # as stored (an email lower-cased, a number written canonically)


@router.put(
    "/{recipient_id}/drafts/{field_id}",
    summary="Save one of this person's values before they submit",
    responses={
        **_DOCUMENT,
        409: {"description": "Locked, not asked, or already signed"},
        422: {"description": "Not a valid value for the field, or too long for its box"},
    },
)
def save_draft(
    recipient_id: uuid.UUID, field_id: uuid.UUID, body: DraftRequest, request: Request
) -> DraftSaved:
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        limits.by_caller(request, "draft", who.caller, recipient_id)
        service.require_ready(uow, who, to_change=True)
        return DraftSaved(value=drafts.save_draft(uow, who, field_id, body.value))


@router.delete(
    "/{recipient_id}/drafts/{field_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear one of this person's values before they submit",
    responses=_DOCUMENT,
)
def clear_draft(recipient_id: uuid.UUID, field_id: uuid.UUID, request: Request) -> None:
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        limits.by_caller(request, "draft", who.caller, recipient_id)
        service.require_ready(uow, who, to_change=True)
        drafts.clear_draft(uow, who, field_id)


@router.post(
    "/{recipient_id}/viewed",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="The document was shown to this person (recorded once)",
    responses=_DOCUMENT,
)
def viewed(recipient_id: uuid.UUID, request: Request) -> None:
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        service.mark_viewed(uow, who)


class SignatureState(BaseModel):
    adopted: list[signatures.Adopted]  # this person's, for this envelope
    saved: list[signatures.Adopted]  # a countersigner's account's, offered to use again
    fonts: list[FontView]  # the handwriting styles a typed signature may take


class Placed(BaseModel):
    placed: int


@router.get(
    "/{recipient_id}/signature",
    summary="This person's adopted signature and initials, and the styles to type one in",
    responses=_DOCUMENT,
)
def signature(recipient_id: uuid.UUID, request: Request, response: Response) -> SignatureState:
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        service.require_ready(uow, who)
        found = signatures.adopted(uow, who.recipient.id)
        user = who.recipient.user_id
        kept = signatures.saved(uow, user) if who.recipient.kind == "countersigner" and user else []
    _no_store(response)
    return SignatureState(
        adopted=list(found.values()), saved=kept, fonts=signatures.signature_fonts()
    )


@router.put(
    "/{recipient_id}/signature/{kind}",
    summary="Adopt (or change) this person's signature or initials for this envelope",
    responses={
        **_DOCUMENT,
        409: {"description": "Already signed"},
        422: {"description": "Why it is not a signature"},
    },
)
def adopt(
    recipient_id: uuid.UUID, kind: signatures.Kind, body: signatures.SignatureIn, request: Request
) -> signatures.Adopted:
    with _db(request).unit_of_work() as uow:
        who = service.locked(uow, service.acting(uow, request, recipient_id))
        service.require_ready(uow, who, to_change=True)
        return signatures.adopt(uow, who.recipient.id, who.recipient.workspace_id, kind, body)


@router.post(
    "/{recipient_id}/apply-all/{kind}",
    summary="Sign every one of this person's places of a kind with their adopted one",
    responses={**_DOCUMENT, 409: {"description": "Nothing adopted yet, or already signed"}},
)
def apply_all(recipient_id: uuid.UUID, kind: signatures.Kind, request: Request) -> Placed:
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        service.require_ready(uow, who, to_change=True)
        return Placed(placed=drafts.apply_all(uow, who, kind))


@router.post(
    "/{recipient_id}/submit",
    summary="Sign and submit: every value checked again, then written once (Idempotency-Key)",
    response_model=submit.Submitted,
    responses={
        **_DOCUMENT,
        409: {"description": "Declined, or not this person's turn"},
        422: {"description": "Each field that needs attention, by its id"},
    },
)
def sign_and_submit(
    recipient_id: uuid.UUID,
    request: Request,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    with _db(request).unit_of_work() as uow:
        caller = service.identify(uow, request, recipient_id)
        guard = guard.for_caller(caller.caller)  # a stored answer only for the one who got it
        if (replay := guard.begin(uow)) is not None:
            return replay
        who = service.may_act(caller)
        limits.by_caller(request, "act", who.caller, recipient_id)
        service.require_ready(uow, who)
        done = submit.submit(uow, who)
        return guard.finish(uow, status.HTTP_200_OK, done.model_dump(mode="json"))


class DeclineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class DeclinedView(BaseModel):
    declined: bool = True


@router.post(
    "/{recipient_id}/decline",
    response_model=DeclinedView,
    summary="Decline to sign, with a reason: final, for everyone (Idempotency-Key)",
    responses={**_DOCUMENT, 409: {"description": "Already signed, or not this person's turn"}},
)
def decline_to_sign(
    recipient_id: uuid.UUID,
    body: DeclineRequest,
    request: Request,
    guard: Annotated[IdempotencyGuard, Depends(idempotency_guard)],
) -> JSONResponse:
    reason = body.reason.strip()
    if not reason:
        raise ValidationFailed([FieldError("reason", "Tell them why")])
    with _db(request).unit_of_work() as uow:
        caller = service.identify(uow, request, recipient_id)
        guard = guard.for_caller(caller.caller)  # a stored answer only for the one who got it
        if (replay := guard.begin(uow)) is not None:
            return replay
        who = service.may_act(caller)
        limits.by_caller(request, "act", who.caller, recipient_id)
        if who.recipient.require_email_code and not who.verified:
            raise VerifyFirst
        decline.decline(uow, who, reason)
        return guard.finish(uow, status.HTTP_200_OK, DeclinedView().model_dump(mode="json"))


@router.get("/{recipient_id}/done", summary="What the done screen says", responses=_DOCUMENT)
def done(recipient_id: uuid.UUID, request: Request, response: Response) -> DoneView:
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        view = service.done(uow, who)
    _no_store(response)
    return view


@router.get(
    "/{recipient_id}/copy.pdf",
    summary="A copy of the document as signed so far, with only what this person may see",
    response_class=Response,
    responses={**_DOCUMENT, 200: {"content": {"application/pdf": {}}}},
)
def copy(recipient_id: uuid.UUID, request: Request) -> Response:
    store: BlobStore = request.app.state.blob_store
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        service.require_ready(uow, who)
        pdf = drawing.signed_pdf(uow, store, who.recipient, viewer=who.recipient)
    name = f"{who.recipient.title} - signed by {who.recipient.name}.pdf"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": attachment(name), "Cache-Control": "no-store"},
    )


@router.get(
    "/{recipient_id}/completed",
    summary="A completed envelope's signed copy, for the colleague who countersigned it",
    response_class=Response,
    responses={
        **_DOCUMENT,
        200: {"content": {"application/pdf": {}}},
        409: {"description": "Not completed"},
    },
)
def completed_copy(
    recipient_id: uuid.UUID, request: Request, part: DownloadPart = "combined"
) -> Response:
    store: BlobStore = request.app.state.blob_store
    with _db(request).unit_of_work() as uow:
        who = service.acting(uow, request, recipient_id)
        if who.recipient.kind != "countersigner":
            raise LinkClosed  # a signer has theirs by email
        pdf, name = read_completed(uow.session, store, who.recipient.envelope_id, part)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": attachment(name), "Cache-Control": "no-store"},
    )
