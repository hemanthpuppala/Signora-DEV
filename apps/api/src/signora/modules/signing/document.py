"""The signer's document (Phase 8 LLD §4.2): every field with what this person may see of it.

The server decides what is sent: a value hidden from a person never leaves the server. Pure.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel

from signora.modules.envelopes import (
    Condition,
    FormField,
    GivenValue,
    Option,
    PageSize,
    Place,
    SignerRecipient,
    form_fields_of,
    name_part,
)
from signora.modules.review import FieldView, RoleView
from signora.modules.review.values import SENSITIVE, ManualHolds
from signora.modules.typesetting import FIT_RULE, FitRule, FontView, font_view

Hidden = Literal["private", "countersigner"]
SIGNS = frozenset({"signature", "initials"})  # placed by a tap (§5.3)
SIGNING_DATE = "date_signed"  # filled at submit (§5.6)


class SignerParty(BaseModel):
    id: uuid.UUID
    label: str
    kind: str  # signer, countersigner, other


class SignerField(BaseModel):
    id: uuid.UUID
    label: str
    holds: ManualHolds
    holds_label: str | None
    format: str | None
    party_id: uuid.UUID | None  # None: filled in before sending
    mine: bool  # this person fills it
    required: bool  # this person must fill it (when it is asked)
    options: list[Option]
    depends_on: Condition | None
    places: list[Place]
    value: str | None  # what this person sees in it
    locked: bool  # given before signing (or their own name): they cannot change it
    draft: str | None  # their saved, unsubmitted value
    hidden: Hidden | None  # why a value is not shown


class SignerDocument(BaseModel):
    pages: list[PageSize]
    parties: list[SignerParty]
    fields: list[SignerField]
    font: FontView
    fit: FitRule


def _private(item: FormField) -> bool:
    return item.holds in SENSITIVE or (item.holds == "other" and item.sensitive)


def _seen(
    item: FormField,
    given: GivenValue | None,
    viewer: SignerRecipient,
    countersigning_parties: frozenset[uuid.UUID],
) -> tuple[str | None, Hidden | None]:
    """What a person sees in a field that is not theirs (§4.2, §7.1.5): a countersigner sees every
    value; a signer never sees a countersigner's, nor someone else's private value."""
    if viewer.kind == "countersigner":
        return (given.value if given else None), None
    if item.party_id in countersigning_parties:
        return None, "countersigner"
    if _private(item):
        return None, "private"
    return (given.value if given else None), None


def build_view(
    *,
    viewer: SignerRecipient,
    pages: Sequence[tuple[float, float]],
    parties: Sequence[RoleView],
    fields: Sequence[FieldView],
    values: Sequence[GivenValue],
    drafts: Mapping[uuid.UUID, str],
) -> SignerDocument:
    """O(F + P + V): one pass over the fields (and their places), values by field id."""
    by_field = {given.field_id: given for given in values}
    required = {field.id: field.required for field in fields}
    countersigning = frozenset(party.id for party in parties if party.kind == "countersigner")
    out: list[SignerField] = []
    for item in form_fields_of(fields):
        given = by_field.get(item.id)
        mine = item.party_id is not None and item.party_id == viewer.party_id
        locked = False
        hidden: Hidden | None = None
        if mine:
            value = given.value if given else None
            locked = given is not None and (
                given.given_by != "recipient" or viewer.status == "signed"
            )
            if value is None and item.from_recipient == "name":
                value, locked = name_part(item.holds, viewer.name), True
        else:
            value, hidden = _seen(item, given, viewer, countersigning)
        out.append(
            SignerField(
                id=item.id,
                label=item.label,
                holds=item.holds,
                holds_label=item.holds_label,
                format=item.format,
                party_id=item.party_id,
                mine=mine,
                required=mine
                and item.holds != SIGNING_DATE
                and (item.holds in SIGNS or required[item.id]),
                options=item.options,
                depends_on=item.depends_on,
                places=item.places,
                value=value,
                locked=locked,
                draft=drafts.get(item.id) if mine and not locked else None,
                hidden=hidden,
            )
        )
    return SignerDocument(
        pages=[PageSize(width=width, height=height) for width, height in pages],
        parties=[SignerParty(id=p.id, label=p.label, kind=p.kind) for p in parties],
        fields=out,
        font=font_view(viewer.font),
        fit=FIT_RULE,
    )
