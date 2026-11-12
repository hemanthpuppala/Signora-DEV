"""How a version's parties and fields read in the API (Phase 5 LLD §5.4; Phase 6 §10)."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel

from signora.modules.review.values import FilledBy, ManualHolds, PartyKind

EMBEDDED_FIELD = re.compile(r"\{f\d+(?:=[^{}]*)?\}")  # a field inside an option's words


def option_words(text: str | None) -> str | None:
    """An option's own words for a person: a field inside them reads as "…"."""
    return EMBEDDED_FIELD.sub("…", text) if text else None


class RoleView(BaseModel):
    id: uuid.UUID
    slug: str
    label: str
    kind: PartyKind  # how it signs
    kind_label: str | None  # the typed text of an Other kind ("Witness")
    position: int
    field_count: int


class PlacementView(BaseModel):
    id: uuid.UUID | None  # none for a place found before the fields were stored
    page: int
    rect: tuple[float, float, float, float]  # PDF points on the page as displayed
    kind: str
    option_value: str | None
    option_text: str | None
    # A dropdown's or a list's own options (the PDF's): what a condition on it may name.
    options: list[str] | None = None
    # The agreement's text size beside it, measured at approval (Phase 7b); none before that
    text_size: float | None = None
    # A signature place's room above it, measured at approval (typesetting.marks); none before
    mark_top: float | None = None


class DependencyView(BaseModel):
    key: str
    option: str


class FieldView(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    holds: ManualHolds  # the contract's enum: the interface's labels must cover it (§1.8)
    holds_label: str | None  # the typed text of an Other type
    format: str | None  # how a date or a part of one is written (7c); its type's default if unset
    filled_by: FilledBy
    role: str | None  # the role's slug when filled_by is "role"
    party_id: uuid.UUID | None  # the same party, by id (what editing uses)
    origin: Literal["detected", "added"]
    required: bool
    sensitive: bool
    depends_on: DependencyView | None
    needs_review: str | None
    placements: list[PlacementView]
