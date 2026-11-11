"""The send form, generated from an approved version (Phase 7 LLD §2, §11, §11.1). Pure.

What it asks: every field someone types (grouped by party, then "before sending"), each signer's
name and email, each countersigner (defaulting to the department's list in order), the settings.
Signatures, initials and signing dates are given by signing, never asked here; a party's name and
email fields come from the person who signs as it (``from_recipient``), never asked either.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from signora.modules.review import FieldView, RoleView
from signora.modules.review.formats import NOT_TYPED
from signora.modules.review.values import SIGNING_PLACES, ManualHolds, choice_options
from signora.modules.typesetting import DEFAULT_FONT, FIT_RULE, FitRule, FontView, font_view

# A party's fields that come from the person signing as it, as DocuSign's Full Name, First Name,
# Last Name and Email fields do (Phase 7b): the email at send, the name at signing (the name they
# sign as, which they may correct). A Legal name may be a company's, so it stays the sender's.
NAME_HOLDS = frozenset({"full_name", "first_name", "last_name"})
EMAIL_HOLDS = frozenset({"email"})
FromRecipient = Literal["name", "email"]


class Option(BaseModel):
    value: str
    text: str


class Condition(BaseModel):
    field_id: uuid.UUID
    option: str


class Place(BaseModel):
    """Where a field's value is drawn: PDF points on the page as displayed."""

    page: int
    rect: tuple[float, float, float, float]
    option_value: str | None  # a choice's place stands for one option
    text_size: float | None  # the agreement's text size beside it (Phase 7b), when measured


class PageSize(BaseModel):
    width: float
    height: float


class FormField(BaseModel):
    id: uuid.UUID
    label: str
    holds: ManualHolds
    holds_label: str | None
    format: str | None  # how a date or a part of one is written on the page (7c)
    party_id: uuid.UUID | None  # None: filled in before sending, or asked of nobody
    required: bool  # only the sender's own required fields: nobody else can fill them (§15.2)
    sensitive: bool
    options: list[Option]  # a choice's options
    depends_on: Condition | None
    places: list[Place]  # where the value shows on the document (the review step)
    from_recipient: FromRecipient | None  # not asked: the party's signer gives it (Phase 7b)


class FormSigner(BaseModel):
    party_id: uuid.UUID
    label: str
    kind_label: str | None  # an Other kind's words ("Witness")
    position: int


class Colleague(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str


class FormCountersigner(BaseModel):
    party_id: uuid.UUID
    label: str
    position: int
    default: Colleague | None  # the department's k-th countersigner, if it has one


class FormSettings(BaseModel):
    require_email_code: bool
    reminder_interval_hours: int
    max_reminders: int
    expiry_days: int
    notify_emails: list[str]


class SendForm(BaseModel):
    document_id: uuid.UUID
    document_name: str
    version_id: uuid.UUID
    version_number: int
    pages: list[PageSize]  # the document's pages as displayed, for the review step
    signers: list[FormSigner]
    countersigners: list[FormCountersigner]
    # Who may be chosen to countersign: the company's active members, by name. Given with the
    # form, so whoever may send can choose one (the members directory has a permission of its own).
    colleagues: list[Colleague]
    fields: list[FormField]
    settings: FormSettings
    font: FontView  # what values are drawn in, and how they fit (Phase 7b)
    fit: FitRule


def options_of(field: FieldView) -> list[Option]:
    """A choice's options, once each and in order (review's one reading of a choice): the option
    each place stands for, and a dropdown's or a list's own."""
    return [
        Option(value=value, text=words)
        for value, words in choice_options(
            (place.option_value, place.option_text, place.options) for place in field.placements
        )
    ]


def places_of(field: FieldView) -> list[Place]:
    """Where a field's value is drawn, one place per box."""
    return [
        Place(
            page=place.page,
            rect=place.rect,
            option_value=place.option_value,
            text_size=place.text_size,
        )
        for place in field.placements
    ]


def from_recipient(field: FieldView) -> FromRecipient | None:
    """Whether a field comes from the person signing as its party, and which of their details."""
    if field.filled_by != "role":
        return None
    if field.holds in NAME_HOLDS:
        return "name"
    if field.holds in EMAIL_HOLDS:
        return "email"
    return None


def signing_parties(fields: Sequence[FieldView]) -> set[uuid.UUID]:
    """The parties that sign: those with a signature or initials place. A party with nowhere to sign
    is never asked to sign (Phase 8): its fields are the sender's to fill. O(F)."""
    return {f.party_id for f in fields if f.holds in SIGNING_PLACES and f.party_id is not None}


def form_fields_of(fields: Sequence[FieldView]) -> list[FormField]:
    """Each field as sending and signing read it: what it holds, whose it is, its options, its
    condition and its places. O(F), with an index by key for conditions. A condition on a field
    outside ``fields`` is dropped (it cannot be met). A field of a party with nowhere to sign is the
    sender's: filled in before sending, required as the template says."""
    id_of_key = {field.key: field.id for field in fields}
    signing = signing_parties(fields)

    def theirs(field: FieldView) -> bool:
        return field.filled_by == "role" and field.party_id in signing

    return [
        FormField(
            id=field.id,
            label=field.label,
            holds=field.holds,
            holds_label=field.holds_label,
            format=field.format,
            party_id=field.party_id if theirs(field) else None,
            required=not theirs(field) and field.filled_by != "none" and field.required,
            from_recipient=from_recipient(field) if theirs(field) else None,
            sensitive=field.sensitive,
            options=options_of(field) if field.holds == "choice" else [],
            places=places_of(field),
            depends_on=Condition(
                field_id=id_of_key[field.depends_on.key], option=field.depends_on.option
            )
            if field.depends_on and field.depends_on.key in id_of_key
            else None,
        )
        for field in fields
    ]


def build_form(
    *,
    document_id: uuid.UUID,
    document_name: str,
    version_id: uuid.UUID,
    version_number: int,
    pages: Sequence[tuple[float, float]],
    parties: Sequence[RoleView],
    fields: Sequence[FieldView],
    countersigners: Sequence[Colleague],
    colleagues: Sequence[Colleague],
    settings: FormSettings,
) -> SendForm:
    """O(R + F): one pass over the parties and one over the fields, with an index by key."""
    signing = signing_parties(fields)
    ordered = [p for p in sorted(parties, key=lambda party: party.position) if p.id in signing]

    signers = [
        FormSigner(
            party_id=party.id,
            label=party.label,
            kind_label=party.kind_label,
            position=party.position,
        )
        for party in ordered
        if party.kind == "signer"
    ]
    firm = [party for party in ordered if party.kind == "countersigner"]
    countersigning = [
        FormCountersigner(
            party_id=party.id,
            label=party.label,
            position=party.position,
            default=countersigners[index] if index < len(countersigners) else None,
        )
        for index, party in enumerate(firm)
    ]
    form_fields = [item for item in form_fields_of(fields) if item.holds not in NOT_TYPED]
    return SendForm(
        document_id=document_id,
        document_name=document_name,
        version_id=version_id,
        version_number=version_number,
        pages=[PageSize(width=width, height=height) for width, height in pages],
        signers=signers,
        countersigners=countersigning,
        colleagues=list(colleagues),
        fields=form_fields,
        settings=settings,
        font=font_view(DEFAULT_FONT),
        fit=FIT_RULE,
    )
