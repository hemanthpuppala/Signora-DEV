"""What a signed PDF draws (Phase 8 LLD §10.1): every value an envelope holds, or only what one
person may see (their copy so far), turned into the renderer's items by the same rules as the
preview: each value as its field writes it, in each place it is written in, at that place's size.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from signora.kernel.blobstore import BlobStore
from signora.kernel.db import UnitOfWork
from signora.modules.documents import version_for_signing
from signora.modules.envelopes import (
    FormField,
    GivenValue,
    SignerRecipient,
    envelope_values,
    form_fields_of,
    written_in,
)
from signora.modules.rendering import DrawnSignature, Item, Mark, Text, TypedSignature, render
from signora.modules.review import read_set
from signora.modules.review.formats import written
from signora.modules.review.values import SIGNING_PLACES
from signora.modules.signing.document import build_view
from signora.modules.typesetting import place_size


def _signatures(uow: UnitOfWork, values: Sequence[GivenValue]) -> dict[tuple[uuid.UUID, str], Any]:
    """The adopted signatures the values name, by (recipient, kind): one read."""
    recipients = list(
        {
            v.recipient_id
            for v in values
            if v.recipient_id and v.value.startswith(("signature:", "initials:"))
        }
    )
    if not recipients:
        return {}
    rows = uow.session.execute(
        text(
            "SELECT recipient_id, kind, method, text, font, strokes, sha256 "
            "FROM signing_signatures WHERE recipient_id = ANY(:r)"
        ),
        {"r": recipients},
    )
    return {(row.recipient_id, row.kind): row for row in rows}


def _items(field: FormField, value: str, font: str, mark: Any) -> list[Item]:
    places = field.places
    if field.holds in SIGNING_PLACES:
        if mark is None:
            return []
        out: list[Item] = []
        for place in places:
            x0, y0, x1, y1 = place.rect
            # Grown to a readable height, never over the agreement's text (typesetting.mark_top).
            rect = (x0, place.mark_top if place.mark_top is not None else y0, x1, y1)
            initials = field.holds == "initials"
            signature_id = bytes(mark.sha256).hex()[:16]
            if mark.method == "typed":
                out.append(
                    TypedSignature(place.page, rect, mark.text, mark.font, signature_id, initials)
                )
            else:
                strokes = [[(int(x), int(y)) for x, y in stroke] for stroke in mark.strokes]
                out.append(DrawnSignature(place.page, rect, strokes, signature_id, initials))
        return out
    if field.holds == "checkbox":
        return [Mark(p.page, p.rect) for p in places] if value == "true" else []
    out = []
    if field.holds == "choice":
        out += [Mark(p.page, p.rect) for p in places if p.option_value == value]
        words = next((o.text for o in field.options if o.value == value), value)
    else:
        words = written(field.holds, value, field.format)
    for place in written_in(field):
        out.append(
            Text(place.page, place.rect, words, place_size(place.text_size, place.rect), font)
        )
    return out


def collect(
    uow: UnitOfWork, store: BlobStore, recipient: SignerRecipient, *, viewer: SignerRecipient | None
) -> tuple[bytes, list[Item]]:
    """The version's PDF and what to write in it: every value (``viewer`` None: the completed
    document) or only those ``viewer`` may see (their copy as signed so far). Reads only."""
    version = version_for_signing(uow.session, recipient.version_id)
    parties, fields = read_set(uow.session, recipient.version_id)
    values = envelope_values(uow.session, recipient.envelope_id)
    visible = {v.field_id: v.value for v in values}
    if viewer is not None:
        view = build_view(
            viewer=viewer, pages=[], parties=parties, fields=fields, values=values, drafts={}
        )
        visible = {f.id: f.value for f in view.fields if f.value and f.id in visible}
    by_field = {v.field_id: v for v in values}
    marks = _signatures(uow, values)
    items: list[Item] = []
    for field in form_fields_of(fields):
        value = visible.get(field.id)
        if not value:
            continue
        given = by_field[field.id]
        mark = marks.get((given.recipient_id, field.holds)) if given.recipient_id else None
        items += _items(field, value, recipient.font, mark)
    with store.open(version.pdf) as source:
        return source.read(), items


def signed_pdf(
    uow: UnitOfWork, store: BlobStore, recipient: SignerRecipient, *, viewer: SignerRecipient | None
) -> bytes:
    pdf, items = collect(uow, store, recipient, viewer=viewer)
    return render(pdf, items, envelope_id=recipient.envelope_id)
