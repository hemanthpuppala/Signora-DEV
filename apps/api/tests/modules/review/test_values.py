"""One list of values in two layers (Phase 6 LLD §1.8, §4.1)."""

from __future__ import annotations

from typing import get_args

from signora.modules.detection.schema import ALLOWED as AI_ALLOWED
from signora.modules.detection.schema import HOLDS
from signora.modules.review.values import (
    AI_HOLDS,
    ALLOWED,
    MANUAL_HOLDS,
    OWN,
    PARTY_VALUES,
    SENSITIVE,
    SHARED,
    ManualHolds,
    PlaceKind,
    family,
)
from signora.modules.review.views import FieldView


def test_the_manual_layer_is_the_ai_layer_plus_note_and_other() -> None:
    assert MANUAL_HOLDS[: len(AI_HOLDS)] == AI_HOLDS
    assert set(MANUAL_HOLDS) - set(AI_HOLDS) == {"note", "other"}
    assert set(get_args(ManualHolds)) == set(MANUAL_HOLDS)
    assert "url" in AI_HOLDS  # the one addition for the AI (owner decision)


def test_the_ai_is_never_offered_a_manual_only_value() -> None:
    assert HOLDS == AI_HOLDS
    for holds in AI_ALLOWED.values():
        assert holds <= set(AI_HOLDS)
        assert not holds & {"note", "other"}


def test_every_rule_names_only_listed_values_and_every_kind_of_box() -> None:
    for group in (PARTY_VALUES, OWN, SHARED, SENSITIVE):
        assert group <= set(MANUAL_HOLDS)
    assert set(ALLOWED) == set(get_args(PlaceKind))
    assert ALLOWED["blank"] >= {"note", "other", "url"}  # a drawn box takes any typed value
    assert {family(h) for h in ("signature", "initials", "date_signed")} == {"signing"}
    assert {family(h) for h in ("checkbox", "choice")} == {"mark"}
    assert family("email") == "data"


def test_the_api_contract_carries_the_manual_layer() -> None:
    enum = FieldView.model_json_schema()["properties"]["holds"]["enum"]
    assert tuple(enum) == MANUAL_HOLDS
