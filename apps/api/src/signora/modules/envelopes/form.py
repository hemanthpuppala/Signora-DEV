"""The send form, generated from an approved version (Phase 7 LLD §2, §11, §11.1). Pure.

What it asks: every field someone types (grouped by party, then "before sending"), each signer's
name and email, each countersigner (defaulting to the department's list in order), the settings.
Signatures, initials and signing dates are given by signing, never asked here.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from pydantic import BaseModel

from signora.modules.review import FieldView, RoleView
from signora.modules.review.formats import NOT_TYPED
from signora.modules.review.values import ManualHolds

# A signer's name and email fill these of their party's fields when the sender left them empty
# (as DocuSign fills its Full Name, First Name, Last Name and Email fields from the recipient).
NAME_HOLDS = frozenset({"full_name", "first_name", "last_name"})
EMAIL_HOLDS = frozenset({"email"})


class Option(BaseModel):
    value: str
    text: str


class Condition(BaseModel):
    field_id: uuid.UUID
    option: str


class FormField(BaseModel):
    id: uuid.UUID
    label: str
    holds: ManualHolds
    holds_label: str | None
    party_id: uuid.UUID | None  # None: filled in before sending, or asked of nobody
    required: bool  # only the sender's own required fields: nobody else can fill them (§15.2)
    sensitive: bool
    options: list[Option]  # a choice's options
    depends_on: Condition | None


class FormSigner(BaseModel):
    party_id: uuid.UUID
    label: str
    kind_label: str | None  # an Other kind's words ("Witness")
    position: int
    name_field_ids: list[uuid.UUID]  # where their name may already be typed (step 2)
    email_field_ids: list[uuid.UUID]


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
    signers: list[FormSigner]
    countersigners: list[FormCountersigner]
    fields: list[FormField]
    settings: FormSettings


def options_of(field: FieldView) -> list[Option]:
    """A choice's options, once each, in the order of their places."""
    seen: dict[str, Option] = {}
    for place in field.placements:
        if place.option_value and place.option_value not in seen:
            seen[place.option_value] = Option(
                value=place.option_value, text=place.option_text or place.option_value
            )
    return list(seen.values())


def build_form(
    *,
    document_id: uuid.UUID,
    document_name: str,
    version_id: uuid.UUID,
    version_number: int,
    parties: Sequence[RoleView],
    fields: Sequence[FieldView],
    countersigners: Sequence[Colleague],
    settings: FormSettings,
) -> SendForm:
    """O(R + F): one pass over the parties and one over the fields, with an index by key."""
    id_of_key = {field.key: field.id for field in fields}
    typed = [field for field in fields if field.holds not in NOT_TYPED]
    ordered = sorted(parties, key=lambda party: party.position)

    signers = [
        FormSigner(
            party_id=party.id,
            label=party.label,
            kind_label=party.kind_label,
            position=party.position,
            name_field_ids=[
                f.id
                for f in typed
                if f.party_id == party.id and f.holds in NAME_HOLDS | {"party_name"}
            ],
            email_field_ids=[
                f.id for f in typed if f.party_id == party.id and f.holds in EMAIL_HOLDS
            ],
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
    form_fields = [
        FormField(
            id=field.id,
            label=field.label,
            holds=field.holds,
            holds_label=field.holds_label,
            party_id=field.party_id if field.filled_by == "role" else None,
            required=field.filled_by == "sender" and field.required,
            sensitive=field.sensitive,
            options=options_of(field) if field.holds == "choice" else [],
            depends_on=Condition(
                field_id=id_of_key[field.depends_on.key], option=field.depends_on.option
            )
            if field.depends_on and field.depends_on.key in id_of_key
            else None,
        )
        for field in typed
    ]
    return SendForm(
        document_id=document_id,
        document_name=document_name,
        version_id=version_id,
        version_number=version_number,
        signers=signers,
        countersigners=countersigning,
        fields=form_fields,
        settings=settings,
    )
