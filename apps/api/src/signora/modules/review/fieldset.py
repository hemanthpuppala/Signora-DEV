"""A version's whole set as an editor saves it (Phase 6 LLD §10.2): parties, fields and places with
their ids (new ones made in the browser), in the order they are kept. Limits are the API's
boundary (§10.5); rules that span items are checked in ``editing``."""

from __future__ import annotations

import uuid
from typing import get_args

from pydantic import BaseModel, ConfigDict, Field

from signora.modules.review.checks import WarningCode
from signora.modules.review.values import FilledBy, ManualHolds, PartyKind, PlaceKind

MAX_PARTIES = 20
MAX_FIELDS = 2000
MAX_PLACES = 500  # per field
MIN_SIDE = 8.0  # PDF points: the smallest box a person can draw or resize to


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PartyIn(_In):
    id: uuid.UUID
    label: str = Field(min_length=1, max_length=80)
    kind: PartyKind  # how it signs
    kind_label: str | None = Field(default=None, min_length=1, max_length=40)  # Other: "Witness"


class PlaceIn(_In):
    id: uuid.UUID
    page: int = Field(ge=1)
    rect: tuple[float, float, float, float]  # PDF points on the page as displayed
    kind: PlaceKind  # a stored place keeps the PDF's kind; a new one is "blank" (drawn)
    option_value: str | None = Field(default=None, max_length=200)
    option_text: str | None = Field(default=None, max_length=200)


class DependencyIn(_In):
    field_id: uuid.UUID
    option: str = Field(min_length=1, max_length=200)


class FieldIn(_In):
    id: uuid.UUID
    label: str = Field(min_length=1, max_length=120)
    holds: ManualHolds
    holds_label: str | None = Field(default=None, min_length=1, max_length=60)  # Other's text
    filled_by: FilledBy
    party_id: uuid.UUID | None = None
    required: bool
    sensitive: bool = False  # honoured for an Other type; the rest follow review.values
    depends_on: DependencyIn | None = None
    places: list[PlaceIn] = Field(min_length=1, max_length=MAX_PLACES)


class FieldSet(_In):
    revision: int = Field(ge=0)  # the revision the editor started from (§1.6)
    parties: list[PartyIn] = Field(max_length=MAX_PARTIES)  # in signing order
    fields: list[FieldIn] = Field(max_length=MAX_FIELDS)


class ApproveRequest(_In):
    """Approve with the revision the page shows and the warnings the person saw (§2.1): their
    codes as a set, so a page listing ten warnings of three kinds sends what it likes."""

    revision: int = Field(ge=0)
    accepted: set[WarningCode] = Field(max_length=len(get_args(WarningCode)))


class Saved(BaseModel):
    revision: int


class Revised(BaseModel):
    """The version an edit of an approved version became; the page opens it."""

    version_id: uuid.UUID
    number: int
    revision: int
