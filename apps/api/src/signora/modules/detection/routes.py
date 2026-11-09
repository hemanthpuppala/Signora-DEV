"""Detection's API (Phase 5 LLD §1.3, §5.4): run detection by hand, and read a version's fields."""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

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

router = APIRouter(prefix="/api/v1", tags=["detection"])
Member = Annotated[Actor, Depends(current_actor)]
EMBEDDED_FIELD = re.compile(r"\{f\d+(?:=[^{}]*)?\}")  # a field inside an option's words


def _db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def _option_words(text_: str | None) -> str | None:
    """An option's own words for a person: a field inside them reads as "…"."""
    return EMBEDDED_FIELD.sub("…", text_) if text_ else None


class DetectionStarted(BaseModel):
    mode: Literal["resume", "restart", "running"]


class RoleView(BaseModel):
    slug: str
    label: str
    kind: Literal["signer", "countersigner"]
    position: int
    field_count: int


class PlacementView(BaseModel):
    page: int
    rect: tuple[float, float, float, float]  # PDF points on the page as displayed
    kind: str
    option_value: str | None
    option_text: str | None


class DependencyView(BaseModel):
    key: str
    option: str


class FieldView(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    holds: str
    filled_by: Literal["role", "sender", "none"]
    role: str | None  # the role's slug when filled_by is "role"
    required: bool
    sensitive: bool
    depends_on: DependencyView | None
    needs_review: str | None
    placements: list[PlacementView]


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


def _fields(session: Session, version_id: uuid.UUID) -> tuple[list[RoleView], list[FieldView]]:
    """Two indexed queries, O(F + P) (§5.4)."""
    fields: dict[uuid.UUID, dict[str, Any]] = {}
    for row in session.execute(
        text(
            "SELECT f.id, f.key, f.label, f.holds, f.filled_by, r.slug AS role, f.required, "
            "f.sensitive, d.key AS depends_key, f.depends_on_option, f.needs_review "
            "FROM version_fields f LEFT JOIN version_roles r ON r.id = f.role_id "
            "LEFT JOIN version_fields d ON d.id = f.depends_on_field_id "
            "WHERE f.version_id = :v ORDER BY f.id"
        ),
        {"v": version_id},
    ):
        fields[row.id] = {
            "id": row.id,
            "key": row.key,
            "label": row.label,
            "holds": row.holds,
            "filled_by": row.filled_by,
            "role": row.role,
            "required": row.required,
            "sensitive": row.sensitive,
            "depends_on": DependencyView(key=row.depends_key, option=row.depends_on_option)
            if row.depends_key
            else None,
            "needs_review": row.needs_review,
            "placements": [],
        }
    for row in session.execute(
        text(
            "SELECT field_id, page, x0, y0, x1, y1, kind, option_value, option_text "
            "FROM field_placements WHERE version_id = :v ORDER BY page, y0, x0"
        ),
        {"v": version_id},
    ):
        fields[row.field_id]["placements"].append(
            PlacementView(
                page=row.page,
                rect=(row.x0, row.y0, row.x1, row.y1),
                kind=row.kind,
                option_value=row.option_value,
                option_text=_option_words(row.option_text),
            )
        )
    views = sorted(
        (FieldView(**field) for field in fields.values()),
        key=lambda f: (
            (f.placements[0].page, f.placements[0].rect[1], f.placements[0].rect[0])
            if f.placements
            else (0, 0.0, 0.0)
        ),
    )
    counts: dict[str, int] = {}
    for view in views:
        if view.role:
            counts[view.role] = counts.get(view.role, 0) + 1
    roles = [
        RoleView(
            slug=row.slug,
            label=row.label,
            kind=row.kind,
            position=row.position,
            field_count=counts.get(row.slug, 0),
        )
        for row in session.execute(
            text(
                "SELECT slug, label, kind, position FROM version_roles "
                "WHERE version_id = :v ORDER BY position"
            ),
            {"v": version_id},
        )
    ]
    return roles, views


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
                    page=p.page,
                    rect=p.rect,
                    kind=field.kind,
                    option_value=p.value,
                    option_text=_option_words(p.option_text),
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
        roles, fields = _fields(session, version_id) if state == "ready" else ([], [])
        pending = _pending(run.parsed) if run is not None and state == "detecting" else []
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
            found_again_failed=detection_failure_message(run.failure_code)
            if run is not None and state == "ready" and run.failure_code
            else None,
        )
