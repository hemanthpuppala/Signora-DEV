"""A person's values before they submit (Phase 8 LLD §4.5, §4.7): checked as they are saved by the
same rules as the send and the submit, and seen by nobody else.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, NotFound, ValidationFailed
from signora.modules.envelopes import FormField, asked, envelope_values, fits, form_fields_of
from signora.modules.identity_access import normalize_email
from signora.modules.review import read_set
from signora.modules.review.formats import InvalidValueError, check_value
from signora.modules.signing.document import build_view
from signora.modules.signing.errors import FieldLocked, FieldNotAsked, NotYours
from signora.modules.signing.service import Signer, read_drafts

Values = dict[uuid.UUID, str]


def _merged(uow: UnitOfWork, who: Signer) -> tuple[list[FormField], Values, set[uuid.UUID]]:
    """The version's fields, every value the envelope holds with this person's drafts over it,
    and which of their fields are locked."""
    recipient = who.recipient
    parties, fields = read_set(uow.session, recipient.version_id)
    values = envelope_values(uow.session, recipient.envelope_id)
    drafts = read_drafts(uow, recipient.id)
    view = build_view(
        viewer=recipient, pages=[], parties=parties, fields=fields, values=values, drafts=drafts
    )
    merged = {given.field_id: given.value for given in values}
    locked = {field.id for field in view.fields if field.mine and field.locked}
    merged.update({field.id: field.value for field in view.fields if field.locked and field.value})
    merged.update({field_id: value for field_id, value in drafts.items() if field_id not in locked})
    return form_fields_of(fields), merged, locked


def _drop_unasked(uow: UnitOfWork, who: Signer, items: list[FormField], merged: Values) -> None:
    """A draft whose field is no longer asked goes with it (§4.5)."""
    still = asked(items, merged)
    mine = [item.id for item in items if item.party_id == who.recipient.party_id]
    gone = [field_id for field_id in mine if field_id not in still]
    if gone:
        uow.session.execute(
            text("DELETE FROM signing_drafts WHERE recipient_id = :r AND field_id = ANY(:f)"),
            {"r": who.recipient.id, "f": gone},
        )


def _mine(
    who: Signer, items: list[FormField], field_id: uuid.UUID, locked: set[uuid.UUID]
) -> FormField:
    item = next((candidate for candidate in items if candidate.id == field_id), None)
    if item is None:
        raise NotFound
    if item.party_id is None or item.party_id != who.recipient.party_id:
        raise NotYours
    if field_id in locked:
        raise FieldLocked
    return item


def save_draft(uow: UnitOfWork, who: Signer, field_id: uuid.UUID, raw: str) -> str:
    """Check a value by the one rule (``check_value``) and the fit check, then keep it. Returns
    the value as stored. O(F + P + V)."""
    items, merged, locked = _merged(uow, who)
    item = _mine(who, items, field_id, locked)
    try:
        value = check_value(
            item.holds,
            raw,
            options=[option.value for option in item.options],
            normalize_email=normalize_email,
        )
    except InvalidValueError as error:
        raise ValidationFailed([FieldError("value", str(error))]) from error
    if not fits(item, value, who.recipient.font):
        raise ValidationFailed([FieldError("value", "Too long for its box")])
    merged[field_id] = value
    if field_id not in asked(items, merged):
        raise FieldNotAsked
    uow.session.execute(
        text(
            """
            INSERT INTO signing_drafts (recipient_id, workspace_id, version_id, field_id, value)
            VALUES (:r, :w, :v, :f, :value)
            ON CONFLICT (recipient_id, field_id)
            DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """
        ),
        {
            "r": who.recipient.id,
            "w": who.recipient.workspace_id,
            "v": who.recipient.version_id,
            "f": field_id,
            "value": value,
        },
    )
    _drop_unasked(uow, who, items, merged)
    return value


def clear_draft(uow: UnitOfWork, who: Signer, field_id: uuid.UUID) -> None:
    items, merged, locked = _merged(uow, who)
    _mine(who, items, field_id, locked)
    uow.session.execute(
        text("DELETE FROM signing_drafts WHERE recipient_id = :r AND field_id = :f"),
        {"r": who.recipient.id, "f": field_id},
    )
    merged.pop(field_id, None)
    _drop_unasked(uow, who, items, merged)
