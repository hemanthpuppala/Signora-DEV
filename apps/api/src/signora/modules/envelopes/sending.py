"""A send checked against its form and turned into what is written (Phase 7 LLD §2, §10.1, §11).

Pure: the form (what the version asks), the request, the colleagues who may countersign and the
email normaliser in; a plan out, or every problem at once, each naming its item. One pass with
maps by id: O(R + F + V).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from signora.kernel.errors import FieldError, ValidationFailed
from signora.modules.envelopes.form import Colleague, FormField, SendForm
from signora.modules.review.formats import (
    InvalidValueError,
    check_value,
    check_written,
    written,
)
from signora.modules.typesetting import fitted_size, place_size

MAX_COPIES = 10


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignerIn(_In):
    party_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)


class CountersignerIn(_In):
    party_id: uuid.UUID
    user_id: uuid.UUID


class CopyIn(_In):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)


class ValueIn(_In):
    field_id: uuid.UUID
    value: str = Field(max_length=2000)


class SettingsIn(_In):
    require_email_code: bool = True
    reminder_interval_hours: int = Field(ge=1, le=720)
    max_reminders: int = Field(ge=0, le=20)
    expiry_days: int = Field(ge=1, le=365)
    notify_emails: list[str] = Field(default_factory=list, max_length=5)


class SendRequest(_In):
    version_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=120)
    signers: list[SignerIn] = Field(max_length=20)
    countersigners: list[CountersignerIn] = Field(default_factory=list, max_length=20)
    copies: list[CopyIn] = Field(default_factory=list, max_length=MAX_COPIES)
    values: list[ValueIn] = Field(default_factory=list, max_length=2000)
    settings: SettingsIn
    # One person on two parties (the same email twice) is allowed once the sender confirms it.
    confirm_same_person: bool = False


@dataclass(frozen=True)
class Person:
    name: str
    email: str
    party_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


@dataclass
class Plan:
    """What a valid send writes."""

    title: str
    signers: list[Person]  # in signing order
    countersigners: list[Person]
    copies: list[Person]
    values: dict[uuid.UUID, str]  # the sender's own
    prefill: dict[uuid.UUID, dict[uuid.UUID, str]]  # per party: its recipient's email
    notify_emails: list[str]
    shared_emails: list[str] = field(default_factory=list)  # the same person on two parties


def _asked(item: FormField, values: Mapping[uuid.UUID, str]) -> bool:
    """A field under a condition is asked only when its choice has that option (or its checkbox is
    ticked)."""
    if item.depends_on is None:
        return True
    given = values.get(item.depends_on.field_id)
    return given == item.depends_on.option or (
        item.depends_on.option == "checked" and given == "true"
    )


def prefill(
    fields: Iterable[FormField], party_id: uuid.UUID, person: Person
) -> dict[uuid.UUID, str]:
    """What a recipient's details fill at send, as DocuSign's Email field shows the recipient's
    email: their email in each of their party's Email fields. Their name fields are not filled
    here: they show the name they sign as, at signing (Phase 7b)."""
    return {
        item.id: person.email
        for item in fields
        if item.party_id == party_id and item.from_recipient == "email"
    }


MARKS = frozenset({"checkbox", "choice"})  # drawn as a tick, never as text


def fits(item: FormField, value: str, font_id: str) -> bool:
    """Whether a value can be drawn in every place of its field (Phase 7b), written as its field
    writes it (7c): at the agreement's text size, or smaller down to the smallest readable size.
    Marks are ticks, always fitting."""
    if item.holds in MARKS:
        return True
    text = written(item.holds, value, item.format)
    return all(
        fitted_size(text, place.rect, place_size(place.text_size, place.rect), font_id) is not None
        for place in item.places
    )


def split_name(name: str) -> tuple[str, str]:
    """First and last name at the last space ("Maya van Dijk" → "Maya van", "Dijk"), as DocuSign
    fills its First and Last Name fields; a single word is a first name."""
    first, _, last = name.strip().rpartition(" ")
    return (first, last) if first else (last, "")


def plan_send(
    form: SendForm,
    request: SendRequest,
    *,
    colleagues: Mapping[uuid.UUID, Colleague],
    normalize_email: Callable[[str], str],
) -> Plan:
    errors: list[FieldError] = []

    def email(path: str, raw: str) -> str:
        try:
            return normalize_email(raw)
        except ValueError:
            errors.append(FieldError(path, "Enter a valid email address"))
            return raw

    # Signers: every signer party exactly once, in signing order.
    order = {signer.party_id: signer for signer in form.signers}
    given_signers: dict[uuid.UUID, Person] = {}
    for i, signer in enumerate(request.signers):
        if signer.party_id not in order:
            errors.append(FieldError(f"signers[{i}].party_id", "Not a signer of this document"))
            continue
        if signer.party_id in given_signers:
            errors.append(FieldError(f"signers[{i}].party_id", "This party is given twice"))
            continue
        name = signer.name.strip()
        if not name:
            errors.append(FieldError(f"signers[{i}].name", "Enter a name"))
        given_signers[signer.party_id] = Person(
            name, email(f"signers[{i}].email", signer.email), party_id=signer.party_id
        )
    for party in form.signers:
        if party.party_id not in given_signers:
            errors.append(
                FieldError(f"parties.{party.party_id}", f"Add who signs as {party.label}")
            )

    # Countersigners: every countersigner party exactly once, a colleague of the company.
    firm = {party.party_id for party in form.countersigners}
    given_firm: dict[uuid.UUID, Person] = {}
    for i, countersigner in enumerate(request.countersigners):
        colleague = colleagues.get(countersigner.user_id)
        if countersigner.party_id not in firm:
            errors.append(
                FieldError(f"countersigners[{i}].party_id", "Not a countersigner of this document")
            )
        elif countersigner.party_id in given_firm:
            errors.append(FieldError(f"countersigners[{i}].party_id", "This party is given twice"))
        elif colleague is None:
            errors.append(FieldError(f"countersigners[{i}].user_id", "Choose a colleague"))
        else:
            given_firm[countersigner.party_id] = Person(
                colleague.name,
                colleague.email,
                party_id=countersigner.party_id,
                user_id=colleague.user_id,
            )
    for firm_party in form.countersigners:
        if firm_party.party_id not in given_firm:
            errors.append(
                FieldError(
                    f"parties.{firm_party.party_id}",
                    f"Choose who countersigns as {firm_party.label}",
                )
            )

    copies = [
        Person(copy.name.strip(), email(f"copies[{i}].email", copy.email))
        for i, copy in enumerate(request.copies)
    ]

    # Values: known fields, valid for their type; the sender's required fields when asked.
    by_id = {item.id: item for item in form.fields}
    values: dict[uuid.UUID, str] = {}
    invalid: dict[uuid.UUID, str] = {}  # what is wrong with a value, named once
    raw = {value.field_id: (i, value.value) for i, value in enumerate(request.values)}
    for field_id, (i, text) in raw.items():
        item = by_id.get(field_id)
        if item is None:
            errors.append(FieldError(f"values[{i}].field_id", "Not a field of this document"))
            continue
        if not text.strip():
            continue  # left for the signer (prefilling is optional, §2)
        if item.from_recipient is not None:
            errors.append(FieldError(f"fields.{field_id}", "Filled in from the signer"))
            continue
        try:
            values[field_id] = check_value(
                item.holds,
                text,
                options=[option.value for option in item.options],
                normalize_email=normalize_email,
            )
            check_written(item.holds, values[field_id], item.format)
        except InvalidValueError as error:
            values.pop(field_id, None)
            invalid[field_id] = str(error)
    for item in form.fields:
        if item.id not in values or _asked(item, values):
            continue
        del values[item.id]  # its condition is not met: never asked, never sent
    # Only what is asked is judged: a value left in a field its condition has since hidden is
    # dropped above, never a reason to refuse the send.
    for item in form.fields:
        if not _asked(item, values):
            continue
        if item.id in invalid:
            errors.append(FieldError(f"fields.{item.id}", invalid[item.id]))
        elif item.id in values:
            if not fits(item, values[item.id], form.font.id):
                errors.append(FieldError(f"fields.{item.id}", "Too long for its box"))
        elif item.required:
            errors.append(FieldError(f"fields.{item.id}", "Fill this in before sending"))

    # Prefill: each signer's and countersigner's email in their party's Email fields.
    prefilled = {
        party_id: prefill(form.fields, party_id, person)
        for party_id, person in (*given_signers.items(), *given_firm.items())
    }

    notify = [
        email(f"settings.notify_emails[{i}]", raw)
        for i, raw in enumerate(request.settings.notify_emails)
    ]
    if errors:
        raise ValidationFailed(errors)

    signers = [given_signers[party.party_id] for party in form.signers]
    countersigners = [given_firm[firm_party.party_id] for firm_party in form.countersigners]
    seen: dict[str, int] = {}
    for person in (*signers, *countersigners):
        seen[person.email] = seen.get(person.email, 0) + 1
    title = (request.title or "").strip() or (
        f"{form.document_name} · {signers[0].name}" if signers else form.document_name
    )
    return Plan(
        title=title[:120],
        signers=signers,
        countersigners=countersigners,
        copies=copies,
        values=values,
        prefill=prefilled,
        notify_emails=list(dict.fromkeys(notify)),
        shared_emails=sorted(address for address, count in seen.items() if count > 1),
    )
