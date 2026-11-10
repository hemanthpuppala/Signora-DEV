"""A version's parties and fields as detection proposes them (ADR-R1): review stores them without
knowing how they were found."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProposedParty:
    slug: str
    label: str
    kind: str  # signer or countersigner
    position: int


@dataclass(frozen=True)
class ProposedPlace:
    page: int
    rect: tuple[float, float, float, float]  # PDF points on the page as displayed
    kind: str
    pdf_field: str | None = None
    option_value: str | None = None
    option_text: str | None = None


@dataclass(frozen=True)
class ProposedField:
    key: str
    label: str
    holds: str
    filled_by: str  # role, sender or none
    party: str | None  # the party's slug when filled by a party
    required: bool
    sensitive: bool
    needs_review: str | None
    depends_on: tuple[str, str] | None  # (the key it depends on, the option)
    places: list[ProposedPlace] = field(default_factory=list)
    format: str | None = None  # how a date or a part of one is written (7c); the type's default


@dataclass(frozen=True)
class Proposal:
    parties: list[ProposedParty]
    fields: list[ProposedField]
    flags: dict[str, bool] = field(default_factory=dict)  # the document's, as detection found them
