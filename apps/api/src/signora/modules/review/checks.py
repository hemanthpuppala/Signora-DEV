"""What a person should know before approving (Phase 6 LLD §2.1): warnings, never blocks.

Computed only here, from a version's parties, fields and flags; the fields endpoint lists them and
approval records which were accepted. O(F + P log P + K) for F fields, P places and K overlapping
pairs (§11).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from signora.modules.review.values import OWN, SENSITIVE, SIGNING_PLACES
from signora.modules.review.views import FieldView, RoleView

WarningCode = Literal[
    "no_signer",
    "party_cannot_sign",
    "own_value_not_a_partys",
    "needs_a_look",
    "already_signed",
    "xfa",
    "addressed_to_ai",
    "overlapping_places",
    "private_value",
]

# The document's flags (as detection found them) that are warnings, in plain words.
FLAG_WARNINGS: dict[WarningCode, str] = {
    "already_signed": "This PDF is already signed: filling it in breaks that signature",
    "xfa": "This PDF is an XFA form: what Acrobat shows may differ from these fields",
    "addressed_to_ai": "This document contains text addressed to an AI: check its fields with care",
}


class ReviewWarning(BaseModel):
    code: WarningCode
    message: str
    field_id: uuid.UUID | None = None
    party_id: uuid.UUID | None = None
    count: int | None = None


def warnings_for(
    parties: Sequence[RoleView], fields: Sequence[FieldView], flags: Mapping[str, bool]
) -> list[ReviewWarning]:
    found: list[ReviewWarning] = []
    if not parties:
        found.append(ReviewWarning(code="no_signer", message="No party signs this version"))
    elif not any(party.kind == "signer" for party in parties):
        # Countersigners sign after the signers. With none their turn begins when it is sent,
        # which is worth a look: a template is usually signed by someone outside first.
        found.append(
            ReviewWarning(code="no_signer", message="Every party countersigns: nobody signs first")
        )
    signs = {f.party_id for f in fields if f.holds in SIGNING_PLACES and f.party_id is not None}
    for party in parties:
        if party.id not in signs:
            found.append(
                ReviewWarning(
                    code="party_cannot_sign",
                    message=f"{party.label} has no place to sign: they won't be asked to sign, "
                    "and their fields are filled in when sending",
                    party_id=party.id,
                )
            )
    for field in fields:
        if field.holds in OWN and field.filled_by != "role":
            found.append(
                ReviewWarning(
                    code="own_value_not_a_partys",
                    message=f"{field.label} is a party's own value, but no party fills it",
                    field_id=field.id,
                )
            )
    flagged = sum(1 for f in fields if f.needs_review)
    if flagged:
        noun = "field still needs" if flagged == 1 else "fields still need"
        found.append(
            ReviewWarning(
                code="needs_a_look",
                message=f"{flagged} {noun} a look; approving accepts them as found",
                count=flagged,
            )
        )
    for code, message in FLAG_WARNINGS.items():
        if flags.get(code):
            found.append(ReviewWarning(code=code, message=message))
    found.extend(_overlaps(fields))
    for field in fields:
        if field.holds in SENSITIVE or (field.holds == "other" and field.sensitive):
            found.append(
                ReviewWarning(
                    code="private_value",
                    message=f"{field.label} is private: only the party who gives it sees it",
                    field_id=field.id,
                )
            )
    return found


@dataclass(frozen=True, order=True)
class _Box:
    x0: float
    y0: float
    x1: float
    y1: float
    field_id: uuid.UUID
    label: str


def _overlaps(fields: Sequence[FieldView]) -> list[ReviewWarning]:
    """Places of different fields that overlap on a page: per page, sort by left edge and sweep,
    keeping only the boxes still reaching past the current left edge; each pair warns once."""
    by_page: dict[int, list[_Box]] = defaultdict(list)
    for field in fields:
        for place in field.placements:
            by_page[place.page].append(_Box(*place.rect, field.id, field.label))
    pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    found: list[ReviewWarning] = []
    for page, boxes in sorted(by_page.items()):
        boxes.sort()
        reaching: list[_Box] = []
        for box in boxes:
            reaching = [other for other in reaching if other.x1 > box.x0]
            for other in reaching:
                if other.field_id == box.field_id or not (other.y0 < box.y1 and box.y0 < other.y1):
                    continue
                pair = (min(box.field_id, other.field_id), max(box.field_id, other.field_id))
                if pair in pairs:
                    continue
                pairs.add(pair)
                found.append(
                    ReviewWarning(
                        code="overlapping_places",
                        message=f"{box.label} overlaps {other.label} on page {page}",
                        field_id=box.field_id,
                    )
                )
            reaching.append(box)
    return found
