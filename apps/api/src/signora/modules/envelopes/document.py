"""An envelope's document as it is drawn (Phase 7b): its pages, and where each value goes. Pure.

Read to follow a send, not to make one: it asks nothing, and refuses nothing a send would. An
envelope keeps showing its document after the document or its department is archived (sends
already out are unaffected, Phase 4 §1.4).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from pydantic import BaseModel

from signora.modules.envelopes.form import (
    FromRecipient,
    PageSize,
    Place,
    from_recipient,
    places_of,
)
from signora.modules.review import FieldView
from signora.modules.review.formats import NOT_TYPED
from signora.modules.review.values import ManualHolds
from signora.modules.typesetting import FIT_RULE, FitRule


class DrawnField(BaseModel):
    """A field whose value is drawn as text or a mark: what it holds, how, and where."""

    id: uuid.UUID
    holds: ManualHolds
    format: str | None  # how a date or a part of one is written on the page (7c)
    party_id: uuid.UUID | None  # the party that fills it; None: filled in before sending
    from_recipient: FromRecipient | None  # the party's signer gives it (Phase 7b)
    places: list[Place]


class EnvelopeDocument(BaseModel):
    pages: list[PageSize]  # the version's pages as displayed
    fields: list[DrawnField]
    fit: FitRule  # how a value fits its box; the font is the envelope's own


def build_document(
    pages: Sequence[tuple[float, float]], fields: Sequence[FieldView]
) -> EnvelopeDocument:
    """O(F + P): one pass over the fields and their places. Signatures, initials and signing dates
    are not typed values (``NOT_TYPED``): they are drawn by signing."""
    return EnvelopeDocument(
        pages=[PageSize(width=width, height=height) for width, height in pages],
        fields=[
            DrawnField(
                id=field.id,
                holds=field.holds,
                format=field.format,
                party_id=field.party_id if field.filled_by == "role" else None,
                from_recipient=from_recipient(field),
                places=places_of(field),
            )
            for field in fields
            if field.holds not in NOT_TYPED
        ],
        fit=FIT_RULE,
    )
