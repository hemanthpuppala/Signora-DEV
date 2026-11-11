"""The values a version's parties and fields take, defined once (Phase 6 LLD §1.8, §4.1).

Two layers: the **AI layer** is the closed list the AI chooses from (its schema and prompt); the
**manual layer** adds what only a person can choose when editing, ``note`` and ``other`` (with typed
text). The manual layer is built from the AI layer, so a type added for the AI is offered by hand
too. The API's enums and the interface's labels come from these lists. Pure: no database.
"""

from __future__ import annotations

from typing import Literal, get_args

AiHolds = Literal[
    # signing
    "signature",
    "initials",
    "date_signed",
    # who a party is
    "party_name",
    "full_name",
    "first_name",
    "last_name",
    "company",
    "title",
    "date_of_birth",
    # reaching them
    "email",
    "phone",
    "address",
    "city",
    "state",
    "postal_code",
    "country",
    "url",
    # sensitive identifiers
    "tax_id",
    "bank_account",
    # values
    "date",
    # a date the form splits into boxes ("__ day of ____, 20__"): each box holds one part
    "day",
    "month",
    "year",
    "number",
    "currency",
    "amount_in_words",
    "percent",
    "text",
    # marks
    "checkbox",
    "choice",
]
ManualHolds = Literal[AiHolds, "note", "other"]  # note: text shown to the signer; other: typed

AI_HOLDS: tuple[str, ...] = get_args(AiHolds)
MANUAL_HOLDS: tuple[str, ...] = (*AI_HOLDS, "note", "other")

PartyKind = Literal["signer", "countersigner"]  # how a party signs; "Other" is a label on one (§3)
FilledBy = Literal["role", "sender", "none"]  # stored: a party ("role"), the sender, or nobody
PlaceKind = Literal["text", "signature", "checkbox", "radio", "combobox", "listbox", "blank"]

# What each kind of box may hold. A drawn box (blank) holds anything a text box holds; only the
# manual layer can put a note or a typed type there.
_TEXTUAL = frozenset(MANUAL_HOLDS) - {"checkbox", "choice"}
ALLOWED: dict[str, frozenset[str]] = {
    "text": _TEXTUAL,
    "blank": _TEXTUAL,
    "signature": frozenset({"signature", "initials"}),
    "checkbox": frozenset({"checkbox"}),
    "radio": frozenset({"choice"}),
    "combobox": frozenset({"choice"}),
    "listbox": frozenset({"choice"}),
}
# What a person may make each kind of box hold (§4, §5): a PDF's own boxes keep their nature, but a
# blank (drawn by hand, or a gap detection found) can be anything, a checkbox or one option of a
# choice included. Detection keeps ALLOWED, so the AI never turns a blank line into a checkbox.
MANUAL_ALLOWED: dict[str, frozenset[str]] = {**ALLOWED, "blank": frozenset(MANUAL_HOLDS)}


def may_hold(kind: str, holds: str, *, is_option: bool) -> bool:
    """Whether a place of this kind may belong to a field of this type: what a person may choose
    for it (``MANUAL_ALLOWED``), and what detection makes of it. Detection groups a PDF's
    checkboxes that are one question into one choice, each box standing for an option
    (``is_option``: the place has an option value), so such a box holds that choice."""
    return holds in MANUAL_ALLOWED[kind] or (kind == "checkbox" and holds == "choice" and is_option)


# Lengths, one definition for what detection keeps and what a Save accepts: text detection stored
# must never be refused when it is saved back unchanged.
LABEL_MAX = 120  # a field's label
OPTION_MAX = 400  # an option's words; also its value (a grouped checkbox is named by its words)
# Values that belong to a party: keyed under its role (``<role>.<holds>``) when a party gives them.
PARTY_VALUES = frozenset(
    {
        "signature",
        "initials",
        "date_signed",
        "party_name",
        "full_name",
        "first_name",
        "last_name",
        "company",
        "title",
        "date_of_birth",
        "email",
        "phone",
        "address",
        "city",
        "state",
        "postal_code",
        "country",
        "url",
        "tax_id",
        "bank_account",
    }
)
# Only the party itself gives these; anything else a sender may fill in before sending.
OWN = frozenset({"signature", "initials", "date_signed"})
# One value per party wherever it is asked (Phase 5 §4.3).
SHARED = frozenset({"signature", "initials", "date_signed", "party_name"})
# Shown to nobody but the party who gave it (Phase 5 §4.4); an "other" type has its own toggle.
SENSITIVE = frozenset({"tax_id", "bank_account", "date_of_birth"})

# Families for matching places in the review metrics (platform §7.6): signing, a mark, or data.
FAMILY_SIGNING = frozenset({"signature", "initials", "date_signed"})
FAMILY_MARK = frozenset({"checkbox", "choice"})


def family(holds: str) -> str:
    if holds in FAMILY_SIGNING:
        return "signing"
    if holds in FAMILY_MARK:
        return "mark"
    return "data"
