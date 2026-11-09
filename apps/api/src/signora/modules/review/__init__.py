"""Review module: a version's parties, fields and places, editing them, approval and its metrics
(Phase 6 LLD, ADR-R1).

Public interface — other modules import only from here. Detection hands its proposal over with
``replace_fields`` and reads a version's set with ``read_set``; its pure code imports the key
naming from ``review.keys`` directly.
"""

from signora.modules.review.checks import ReviewWarning, warnings_for
from signora.modules.review.proposal import Proposal, ProposedField, ProposedParty, ProposedPlace
from signora.modules.review.store import read_review, read_set, replace_fields
from signora.modules.review.views import (
    DependencyView,
    FieldView,
    PlacementView,
    RoleView,
    option_words,
)

__all__ = [
    "DependencyView",
    "FieldView",
    "PlacementView",
    "Proposal",
    "ProposedField",
    "ProposedParty",
    "ProposedPlace",
    "ReviewWarning",
    "RoleView",
    "option_words",
    "read_review",
    "read_set",
    "replace_fields",
    "warnings_for",
]
