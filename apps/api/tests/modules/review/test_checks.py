"""Warnings before Approve, never blocks (Phase 6 LLD §2.1): one case per code."""

from __future__ import annotations

import uuid
from typing import Any

from signora.modules.review.checks import warnings_for
from signora.modules.review.views import FieldView, PlacementView, RoleView

CLIENT = uuid.uuid4()
FIRM = uuid.uuid4()


def _party(party_id: uuid.UUID, label: str, kind: str = "signer") -> RoleView:
    return RoleView.model_validate(
        {
            "id": party_id,
            "slug": label.lower(),
            "label": label,
            "kind": kind,
            "kind_label": None,
            "position": 1,
            "field_count": 0,
        }
    )


def _field(label: str, holds: str, party: uuid.UUID | None, **extra: Any) -> FieldView:
    page, rect = extra.pop("at", (1, (100.0, 100.0, 200.0, 120.0)))
    return FieldView.model_validate(
        {
            "id": extra.pop("id", uuid.uuid4()),
            "key": label.lower().replace(" ", "_"),
            "label": label,
            "holds": holds,
            "holds_label": extra.pop("holds_label", None),
            "filled_by": extra.pop("filled_by", "role" if party else "sender"),
            "role": None,
            "party_id": party,
            "origin": "detected",
            "required": True,
            "sensitive": extra.pop("sensitive", False),
            "depends_on": None,
            "needs_review": extra.pop("needs_review", None),
            "placements": [
                PlacementView(
                    id=uuid.uuid4(),
                    page=page,
                    rect=rect,
                    kind="text",
                    option_value=None,
                    option_text=None,
                )
            ],
        }
    )


def _codes(*args: Any) -> list[str]:
    return [w.code for w in warnings_for(*args)]


def test_a_clean_version_has_no_warnings() -> None:
    parties = [_party(CLIENT, "Client")]
    fields = [_field("Client signature", "signature", CLIENT)]
    assert warnings_for(parties, fields, {}) == []


def test_nobody_signs_and_a_party_with_nowhere_to_sign() -> None:
    assert _codes([], [_field("Fee", "currency", None)], {}) == ["no_signer"]
    parties = [_party(CLIENT, "Client"), _party(FIRM, "Firm", "countersigner")]
    found = warnings_for(parties, [_field("Client signature", "signature", CLIENT)], {})
    assert [(w.code, w.party_id) for w in found] == [("party_cannot_sign", FIRM)]
    assert found[0].message == "Firm has no place to sign"


def test_a_partys_own_value_filled_by_the_sender_or_nobody() -> None:
    parties = [_party(CLIENT, "Client")]
    fields = [
        _field("Client signature", "signature", CLIENT),
        _field("Date signed", "date_signed", None, filled_by="none", at=(2, (0, 0, 50, 10))),
    ]
    assert _codes(parties, fields, {}) == ["own_value_not_a_partys"]


def test_flagged_fields_are_one_warning_with_their_count() -> None:
    parties = [_party(CLIENT, "Client")]
    fields = [
        _field("Client signature", "signature", CLIENT, needs_review="not assigned"),
        _field("Fee", "currency", None, needs_review="two answers", at=(2, (0, 0, 50, 10))),
    ]
    (warning,) = warnings_for(parties, fields, {})
    assert (warning.code, warning.count) == ("needs_a_look", 2)


def test_the_documents_flags() -> None:
    parties = [_party(CLIENT, "Client")]
    fields = [_field("Client signature", "signature", CLIENT)]
    flags = {"already_signed": True, "xfa": True, "addressed_to_ai": True, "repaired": True}
    assert _codes(parties, fields, flags) == ["already_signed", "xfa", "addressed_to_ai"]


def test_overlapping_places_of_different_fields_warn_once_per_pair() -> None:
    parties = [_party(CLIENT, "Client")]
    signature = _field("Client signature", "signature", CLIENT, at=(1, (100, 100, 200, 120)))
    over = _field("Name", "full_name", CLIENT, at=(1, (150, 110, 250, 130)))
    beside = _field("Title", "title", CLIENT, at=(1, (300, 100, 400, 120)))  # same row, apart
    other_page = _field("Email", "email", CLIENT, at=(2, (150, 110, 250, 130)))
    found = warnings_for(parties, [signature, over, beside, other_page], {})
    assert [w.code for w in found] == ["overlapping_places"]
    assert found[0].message == "Name overlaps Client signature on page 1"


def test_private_values_and_a_typed_type_marked_private() -> None:
    parties = [_party(CLIENT, "Client")]
    fields = [
        _field("Client signature", "signature", CLIENT),
        _field("Tax number", "tax_id", CLIENT, at=(2, (0, 0, 50, 10))),
        _field(
            "Passport",
            "other",
            CLIENT,
            holds_label="Passport",
            sensitive=True,
            at=(3, (0, 0, 50, 10)),
        ),
        _field("Matter", "other", None, holds_label="Matter number", at=(4, (0, 0, 50, 10))),
    ]
    found = warnings_for(parties, fields, {})
    assert [(w.code, w.message.split(" is ")[0]) for w in found] == [
        ("private_value", "Tax number"),
        ("private_value", "Passport"),
    ]
