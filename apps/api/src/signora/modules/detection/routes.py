"""Detection's API (Phase 5 LLD §1.3, §5.4): run detection by hand, and read a version's fields."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from signora.kernel.db import Database
from signora.kernel.errors import NotFound
from signora.modules.detection.reading import Reading
from signora.modules.detection.run import restart_run
from signora.modules.documents import (
    detection_failure_message,
    start_detection,
    version_for_detection,
    version_status,
)
from signora.modules.identity_access import Actor, current_actor
from signora.modules.review import (
    FieldView,
    PlacementView,
    ReviewWarning,
    RoleView,
    option_words,
    read_review,
    read_set,
    warnings_for,
)
from signora.modules.review.formats import FORMATS
from signora.modules.review.values import MANUAL_ALLOWED, MANUAL_HOLDS, ManualHolds, PlaceKind

router = APIRouter(prefix="/api/v1", tags=["detection"])
Member = Annotated[Actor, Depends(current_actor)]


def _db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


class DetectionStarted(BaseModel):
    mode: Literal["resume", "restart", "running"]


class PendingField(BaseModel):
    """A place found by the read stage, before the AI has said who fills it (§6.3)."""

    id: str  # f1, f2, … for this run
    label: str | None
    kind: str
    placements: list[PlacementView]


class Flags(BaseModel):
    no_fields: bool = False
    addressed_to_ai: bool = False
    xfa: bool = False
    already_signed: bool = False
    repaired: bool = False


class VersionFields(BaseModel):
    status: str
    stage: Literal["read", "ai", "derive", "store", "done"] | None  # the run's next stage
    fields_from: Literal["form_fields", "blanks", "none"] | None
    roles: list[RoleView]
    fields: list[FieldView]  # once ready
    pending: list[PendingField]  # while finding fields, once the document has been read
    flags: Flags
    # Finding the fields again stopped; the version kept the fields found before (review fix).
    found_again_failed: str | None = None
    revision: int = 0  # Phase 6 §1.6: a Save or Approve names the revision it started from
    warnings: list[ReviewWarning] = []  # Phase 6 §2.1: before approving, never a block
    # Phase 6 §4: what each kind of box may be made to hold, so the editor offers only those (the
    # rule stays the server's: Save checks it).
    allowed: dict[PlaceKind, list[ManualHolds]] = {
        kind: [holds for holds in MANUAL_HOLDS if holds in allowed]  # type: ignore[misc]
        for kind, allowed in MANUAL_ALLOWED.items()
    }
    # Phase 7c: how each date type may be written, the default first (the rule stays the
    # server's: Save checks it).
    formats: dict[str, list[str]] = {holds: list(fs) for holds, fs in FORMATS.items()}


@router.post(
    "/documents/{document_id}/versions/{version_id}/detection",
    summary="Find a version's fields again, or resume after a failure (repeat-safe)",
    status_code=status.HTTP_202_ACCEPTED,
    responses={200: {"description": "Already finding fields: nothing changed"}},
)
def run_detection_by_hand(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    response: Response,
    actor: Member,
) -> DetectionStarted:
    with _db(request).unit_of_work() as uow:
        mode = start_detection(uow, actor=actor, document_id=document_id, version_id=version_id)
        if mode == "running":
            response.status_code = status.HTTP_200_OK
            return DetectionStarted(mode=mode)
        if mode == "restart":  # a new run from the start; a resume continues the failed one
            version = version_for_detection(uow.session, version_id)
            if version is None:
                raise NotFound
            restart_run(uow.session, version, requested_by=actor.user_id)
    return DetectionStarted(mode=mode)


def _pending(parsed: dict[str, Any] | None) -> list[PendingField]:
    """The read stage's places, to draw while the AI works (§6.3)."""
    if not parsed:
        return []
    reading = Reading.model_validate(parsed)
    return [
        PendingField(
            id=field.id,
            label=field.label,
            kind=field.kind,
            placements=[
                PlacementView(
                    id=None,
                    page=p.page,
                    rect=p.rect,
                    kind=field.kind,
                    option_value=p.value,
                    option_text=option_words(p.option_text),
                )
                for p in field.placements
            ],
        )
        for field in reading.asked
    ]


@router.get(
    "/documents/{document_id}/versions/{version_id}/fields",
    summary="A version's fields, who fills them and where they are; the places found so far "
    "while its fields are being found",
)
def version_fields(
    document_id: uuid.UUID, version_id: uuid.UUID, request: Request, actor: Member
) -> VersionFields:
    with _db(request).unit_of_work() as uow:
        session = uow.session
        state = version_status(session, actor, document_id, version_id)
        run = session.execute(
            text(
                "SELECT stage, fields_from, parsed, result, failure_code FROM detection_runs "
                "WHERE version_id = :v"
            ),
            {"v": version_id},
        ).one_or_none()
        reviewable = state in ("ready", "approved")
        roles, fields = read_set(session, version_id) if reviewable else ([], [])
        revision, kept_flags = read_review(session, version_id)
        pending = _pending(run.parsed) if run is not None and state == "detecting" else []
        # Review keeps the flags with the version (a version made by editing has no run of its own);
        # while fields are being found, the run's are the newest.
        if reviewable:
            found = kept_flags
        else:
            found = (run.result or {}).get("flags", {}) if run is not None else {}
        flags = Flags(**{name: found[name] for name in Flags.model_fields if name in found})
        return VersionFields(
            status=state,
            stage=run.stage if run is not None else None,
            fields_from=run.fields_from if run is not None else None,
            roles=roles,
            fields=fields,
            pending=pending,
            flags=flags,
            revision=revision,
            warnings=warnings_for(roles, fields, kept_flags) if reviewable else [],
            found_again_failed=detection_failure_message(run.failure_code)
            if run is not None and state == "ready" and run.failure_code
            else None,
        )
