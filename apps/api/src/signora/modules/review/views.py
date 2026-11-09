"""How a version's parties and fields read in the API (Phase 5 LLD §5.4; Phase 6 §10)."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel

EMBEDDED_FIELD = re.compile(r"\{f\d+(?:=[^{}]*)?\}")  # a field inside an option's words


def option_words(text: str | None) -> str | None:
    """An option's own words for a person: a field inside them reads as "…"."""
    return EMBEDDED_FIELD.sub("…", text) if text else None


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
