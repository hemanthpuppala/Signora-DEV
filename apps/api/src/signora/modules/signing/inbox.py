"""To countersign (Phase 8 LLD §7.2): a Signora user's own countersigning, across their departments.

Two lists: what waits for them, soonest expiry first (the urgent first), and what they have
countersigned, latest first. Each is one index range on the countersigner's recipients
(``(user_id, status) WHERE kind = 'countersigner'``) with a keyset cursor: O(k) for a page of k.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text

from signora.kernel import search
from signora.kernel.db import Database
from signora.kernel.errors import FieldError, ValidationFailed
from signora.modules.identity_access import Actor, current_actor

router = APIRouter(prefix="/api/v1/me", tags=["signing"])
Member = Annotated[Actor, Depends(current_actor)]
PAGE = 50
State = Literal["waiting", "done"]

_FROM = """
    FROM envelope_recipients r
    JOIN envelopes e ON e.id = r.envelope_id
    JOIN documents d ON d.id = e.document_id
    JOIN departments dep ON dep.id = e.department_id
    WHERE r.kind = 'countersigner' AND r.user_id = :u
"""
# Waiting: their turn (every signer signed, the envelope open, before expiry), not yet signed.
_WAITING = (
    _FROM + " AND r.status IN ('sent', 'opened', 'viewed') AND e.status = 'signed' "
    "AND e.expires_at > now()"
)
_DONE = _FROM + " AND r.status = 'signed'"
_IN_DEPARTMENT = " AND (CAST(:dep AS uuid) IS NULL OR e.department_id = :dep)"
# Searching (ADR S-1), as a department's envelopes are searched: by the envelope's title, its
# template's name, and each signer's (the customer's) name or email; best match first.
_OWN_TEXTS = ("e.title", "d.name")
_PERSON_TEXTS = ("s.name", "s.email")
_SIGNERS = "FROM envelope_recipients s WHERE s.envelope_id = e.id AND s.kind = 'signer'"
_MATCHES = (
    f" AND ({search.matches(_OWN_TEXTS)} OR EXISTS (SELECT 1 {_SIGNERS} "
    f"AND {search.matches(_PERSON_TEXTS)}))"
)
_SCORE = (
    f"GREATEST({search.score(_OWN_TEXTS)}, "
    f"COALESCE((SELECT max({search.score(_PERSON_TEXTS)}) {_SIGNERS}), 0))"
)


# Each list's date (the cursor's key), whether it runs soonest first, and the row's field for it.
_KEYS: dict[State, tuple[str, bool, str]] = {
    "waiting": ("e.expires_at", True, "expires_at"),  # the urgent first
    "done": ("r.signed_at", False, "countersigned_at"),  # the latest first
}


class Waiting(BaseModel):
    recipient_id: uuid.UUID
    envelope_id: uuid.UUID
    title: str
    document_name: str
    department_id: uuid.UUID
    department_name: str
    signers: list[str]
    signed_at: datetime | None  # when the last signer signed: since when it waits for them
    expires_at: datetime
    countersigned_at: datetime | None  # theirs, in the countersigned list
    completed: bool  # the signed copy is made


class DepartmentRef(BaseModel):
    id: uuid.UUID
    name: str


class WaitingPage(BaseModel):
    items: list[Waiting]
    next_cursor: str | None
    total: int  # how many match, across every page
    # The tabs' counts, in the department chosen (if any), whatever the search.
    waiting: int  # how many wait for them
    done: int  # how many they countersigned
    # The departments they countersign in, by name: the inbox's department filter.
    departments: list[DepartmentRef]


class WaitingCount(BaseModel):
    count: int


def _db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def _cursor(raw: str | None) -> tuple[datetime, uuid.UUID] | None:
    if raw is None:
        return None
    try:
        at, _, ident = base64.urlsafe_b64decode(raw.encode()).decode().partition("|")
        return datetime.fromisoformat(at), uuid.UUID(ident)
    except ValueError:
        raise ValidationFailed([FieldError("cursor", "Not a page of this list")]) from None


@router.get(
    "/countersign",
    summary="My countersigning: what waits for me (soonest expiry first), or what I countersigned",
)
def waiting(
    request: Request,
    actor: Member,
    state: State = "waiting",
    cursor: Annotated[str | None, Query(max_length=300)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    department: uuid.UUID | None = None,
) -> WaitingPage:
    """With ``q``: those whose title, template or signer's name or email matches, best match first,
    then in the list's own order (ADR S-1). With ``department``: only that department's."""
    column, soonest, key = _KEYS[state]
    way = "ASC" if soonest else "DESC"
    query = search.normalize(q)
    where = (_WAITING if state == "waiting" else _DONE) + _IN_DEPARTMENT
    params: dict[str, object] = {"u": actor.user_id, "limit": PAGE + 1, "dep": department}
    # The page is chosen from the rows' own columns (x.*): the score is worked out once a row.
    if query is None:
        after = _cursor(cursor)
        score = "NULL"
        then = ">" if soonest else "<"
        beyond = (
            f"(CAST(:at AS timestamptz) IS NULL OR (x.sort_at, x.recipient_id) {then} (:at, :id))"
        )
        order = f"x.sort_at {way}, x.recipient_id {way}"
        params |= {"at": after[0] if after else None, "id": after[1] if after else None}
        listed = where
    else:
        score = _SCORE
        beyond = search.beyond("x.score", "x.sort_at", "x.recipient_id", soonest_first=soonest)
        order = search.order("x.score", "x.sort_at", "x.recipient_id", soonest_first=soonest)
        params |= query.params | search.after_params(search.after(cursor))
        listed = where + _MATCHES
    with _db(request).unit_of_work() as uow:
        if query is not None:
            search.begin(uow.session)
        rows = uow.session.execute(
            text(
                f"""
                SELECT * FROM (
                    SELECT r.id AS recipient_id, e.id AS envelope_id, e.title,
                           d.name AS document_name, e.department_id, dep.name AS department_name,
                           e.expires_at, r.signed_at AS countersigned_at,
                           e.status = 'completed' AS completed, {column} AS sort_at,
                           (SELECT array_agg(s.name ORDER BY s.position) FROM envelope_recipients s
                            WHERE s.envelope_id = e.id AND s.kind = 'signer') AS signers,
                           (SELECT max(s.signed_at) FROM envelope_recipients s
                            WHERE s.envelope_id = e.id AND s.kind = 'signer') AS signed_at,
                           {score} AS score
                    {listed}
                ) x
                WHERE {beyond}
                ORDER BY {order}
                LIMIT :limit
                """  # noqa: S608 - every interpolated part is a constant of this module or search's
            ),
            params,
        ).all()
        counts = uow.session.execute(
            text(
                f"SELECT (SELECT count(*) {listed}) AS total, "
                f"(SELECT count(*) {_WAITING}{_IN_DEPARTMENT}) AS waiting, "
                f"(SELECT count(*) {_DONE}{_IN_DEPARTMENT}) AS done"
            ),
            {k: v for k, v in params.items() if k in {"u", "dep", "search_q", "search_like"}},
        ).one()
        departments = uow.session.execute(
            text(
                "SELECT DISTINCT dep.id, dep.name FROM envelope_recipients r "
                "JOIN envelopes e ON e.id = r.envelope_id "
                "JOIN departments dep ON dep.id = e.department_id "
                "WHERE r.kind = 'countersigner' AND r.user_id = :u ORDER BY dep.name"
            ),
            {"u": actor.user_id},
        ).all()
    more = len(rows) > PAGE
    shown = rows[:PAGE]
    last = shown[-1] if more else None
    if last is None:
        next_cursor = None
    elif query is not None:
        next_cursor = search.cursor(last.score, getattr(last, key), last.recipient_id)
    else:
        next_cursor = base64.urlsafe_b64encode(
            f"{getattr(last, key).isoformat()}|{last.recipient_id}".encode()
        ).decode()
    return WaitingPage(
        items=[
            Waiting(
                recipient_id=row.recipient_id,
                envelope_id=row.envelope_id,
                title=row.title,
                document_name=row.document_name,
                department_id=row.department_id,
                department_name=row.department_name,
                signers=list(row.signers or []),
                signed_at=row.signed_at,
                expires_at=row.expires_at,
                countersigned_at=row.countersigned_at,
                completed=row.completed,
            )
            for row in shown
        ],
        next_cursor=next_cursor,
        total=counts.total,
        waiting=counts.waiting,
        done=counts.done,
        departments=[DepartmentRef(id=row.id, name=row.name) for row in departments],
    )


@router.get("/countersign/count", summary="How many envelopes wait for my countersignature")
def waiting_count(request: Request, actor: Member) -> WaitingCount:
    with _db(request).unit_of_work() as uow:
        count = uow.session.execute(
            text(f"SELECT count(*) {_WAITING}"),
            {"u": actor.user_id},
        ).scalar_one()
    return WaitingCount(count=count)
