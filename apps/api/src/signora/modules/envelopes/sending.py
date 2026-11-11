"""A send checked against its form and turned into what is written (Phase 7 LLD §2, §10.1, §11).

Pure: the form (what the version asks), the request, the colleagues who may countersign and the
email normaliser in; a plan out, or every problem at once, each naming its item. One pass with
maps by id: O(R + F + V).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from signora.kernel.errors import FieldError, ValidationFailed
from signora.modules.envelopes.errors import NobodySigns
from signora.modules.envelopes.form import Colleague, Condition, FormField, Place, SendForm
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


DEFAULT_ZONE = "UTC"


def _is_zone(name: str) -> bool:
    """A place's zone ("America/Los_Angeles") or UTC. The tz database's other files ("localtime",
    the server's own zone; "Factory", no zone at all) are not a sender's."""
    if name != DEFAULT_ZONE and "/" not in name:
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


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
    # The sender's time zone (the browser's IANA name): its emails give dates as the sender sees
    # them in the app. It only words a date, and the sender never typed it, so a name this server
    # does not know (a browser's "Etc/Unknown") takes UTC rather than refusing the send.
    time_zone: str = Field(default=DEFAULT_ZONE, max_length=64)

    @field_validator("time_zone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        return value if _is_zone(value) else DEFAULT_ZONE


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

    @property
    def first(self) -> Literal["signer", "countersigner"]:
        """Whose turn it is when the envelope goes out: the signers', all together; with no signer
        to wait for, the countersigners'. They are written as sent and emailed their links; the
        others wait."""
        return "signer" if self.signers else "countersigner"


def asked(fields: Iterable[FormField], values: Mapping[uuid.UUID, str]) -> set[uuid.UUID]:
    """The fields that are asked, given these values. A field under a condition is asked only when
    the field it depends on is itself asked and holds that option (a checkbox: ticked), so a value
    left in a field that is no longer asked never keeps what depends on it. Each chain is walked
    once, whatever order the fields come in: O(F). The send modal keeps the same rule to show and
    hide fields as they are filled in (the web's ``conditions.askedFields``; both run
    packages/contracts/vectors/conditions.json)."""
    by_id = {item.id: item for item in fields}
    known: dict[uuid.UUID, bool] = {}
    for start in by_id.values():
        path: list[tuple[uuid.UUID, Condition]] = []
        node: FormField | None = start
        while node is not None and node.id not in known:
            if node.depends_on is None:
                known[node.id] = True
                break
            known[node.id] = False  # until its chain is walked; a chain that loops is not asked
            path.append((node.id, node.depends_on))
            node = by_id.get(node.depends_on.field_id)
        met = node is not None and known[node.id]
        for field_id, condition in reversed(path):
            given = values.get(condition.field_id)
            met = met and (
                given == condition.option or (condition.option == "checked" and given == "true")
            )
            known[field_id] = met
    return {field_id for field_id, is_asked in known.items() if is_asked}


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


def written_in(item: FormField) -> list[Place]:
    """The places a field's value is written in as text. A checkbox is a tick. A choice is a tick
    at the place that stands for the chosen option, and the option's words in a place that stands
    for none: a dropdown's or a list's box. Every other value is written in each of its places."""
    if item.holds == "checkbox":
        return []
    if item.holds == "choice":
        return [place for place in item.places if place.option_value is None]
    return item.places


def fits(item: FormField, value: str, font_id: str) -> bool:
    """Whether a value can be drawn in every place it is written in (Phase 7b), as its field
    writes it (7c): at the agreement's text size, or smaller down to the smallest readable size.
    A tick always fits."""
    text = written(item.holds, value, item.format)
    return all(
        fitted_size(text, place.rect, place_size(place.text_size, place.rect), font_id) is not None
        for place in written_in(item)
    )


def split_name(name: str) -> tuple[str, str]:
    """First and last name at the last space ("Maya van Dijk" → "Maya van", "Dijk"); a single
    word is a first name. The preview keeps the same rule (the web's ``typeset.namePart``; both
    run packages/contracts/vectors/names.json)."""
    first, _, last = name.strip().rpartition(" ")
    return (first.rstrip(), last) if first else (last, "")


def name_part(holds: str, name: str) -> str:
    """The part of a person's name a Full, First or Last name field shows (Phase 7b)."""
    first, last = split_name(name)
    return {"full_name": name.strip(), "first_name": first, "last_name": last}[holds]


def plan_send(
    form: SendForm,
    request: SendRequest,
    *,
    colleagues: Mapping[uuid.UUID, Colleague],
    normalize_email: Callable[[str], str],
) -> Plan:
    if not form.signers and not form.countersigners:
        raise NobodySigns  # nothing to send: nobody would be asked to sign

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

    copies: list[Person] = []
    for i, copy in enumerate(request.copies):
        name = copy.name.strip()
        if not name:
            errors.append(FieldError(f"copies[{i}].name", "Enter a name"))
        copies.append(Person(name, email(f"copies[{i}].email", copy.email)))

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
    # Only what is asked is kept and judged: a value left in a field its condition has since hidden
    # is dropped, never sent and never a reason to refuse the send.
    is_asked = asked(form.fields, values)
    values = {field_id: value for field_id, value in values.items() if field_id in is_asked}
    for item in form.fields:
        if item.id not in is_asked:
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
