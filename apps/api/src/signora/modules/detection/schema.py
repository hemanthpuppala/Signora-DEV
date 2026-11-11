"""The AI's answer, defined once in Pydantic (Phase 5 LLD §3.3).

Each key's rules live in its ``Field(description=...)`` (and each object's docstring), which become
the strict JSON schema's descriptions; the system prompt says only how to read the agreement and
what to answer (owner decision). The same models parse the answer. The model is built per document
so a field id can only be one of that document's ids.

No key is named after a JSON-schema keyword (``required``, ``type``, ``enum``, ``properties``,
``items``): the tests named one ``required`` and every answer came back false (§3.3).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from signora.modules.review.formats import ALL_FORMATS
from signora.modules.review.values import (
    AI_HOLDS,
    AiHolds,
    PartyKind,
)
from signora.modules.review.values import ALLOWED as REVIEW_ALLOWED

# The AI layer of review's one list of values (Phase 6 §4.1): closed, never free-form.
Holds = AiHolds
HOLDS: tuple[str, ...] = AI_HOLDS
RoleKind = PartyKind
# The AI layer's boxes hold only its own values: never a note or a typed type.
ALLOWED: dict[str, frozenset[str]] = {
    kind: holds & frozenset(AI_HOLDS) for kind, holds in REVIEW_ALLOWED.items()
}

DateFormat: Any = Literal[ALL_FORMATS]  # how a date or a part of one is written (7c)

HOLDS_HELP = (
    "What the field contains. A text box or blank line may hold any value except checkbox and "
    "choice; a signature box holds signature or initials; a checkbox holds checkbox; a radio "
    "group, "
    "dropdown or list holds choice. party_name: a party's legal name as the agreement names the "
    "party (a person or an organisation, e.g. in 'between ____ (\"Company\")'); full_name: a "
    "person's own name (e.g. 'Print Name' under a signature); company: the organisation a person "
    "works for. address is the street line; city, state, postal_code and country are their own "
    "boxes when the form splits them. tax_id covers SSN, EIN and other tax numbers; bank_account "
    "covers account and routing numbers. amount_in_words is a sum written out ('____ dollars'); "
    "currency is the figure ('$____'). url is a web address. date_signed is the date next to a "
    "signature recording when it was signed; date is any other date in one box. day, month and "
    "year are the parts of a date the form splits into separate boxes ('the __ day of ____, "
    "20__'): one field per box, each holding its part. text when nothing else fits."
)
FORMAT_HELP = (
    "How the blank writes a date or a part of one, for holds date, date_signed, date_of_birth, "
    "day, month or year; null for every other type. Read it from the blank and the words printed "
    "around it. A whole date: 'MM/DD/YYYY' or 'DD/MM/YYYY' (slashes, four-digit year), "
    "'MM/DD/YY' or 'DD/MM/YY' (two-digit year), 'YYYY-MM-DD', 'D Month YYYY' (9 November 2026), "
    "or 'Month D, YYYY' (November 9, 2026), the format for a plain 'Date: ______' and any date "
    "blank with no cue, a signing date included. Day order: "
    "month first unless the text or the parties are clearly day-first. A day: 'Dth' when it "
    "reads as an ordinal ('this ____ day of' gives 'the 9th day of'), else 'D'. A month: 'Month' "
    "when written as a word ('day of ________, 20__'), 'MM' when a number ('__/__/____'). A "
    "year: 'YY' when two digits complete a printed century ('20____'), else 'YYYY'."
)
FILLED_BY_HELP = (
    "Who fills it. Exactly one of: a slug listed in roles, when that party fills it while signing; "
    "'sender', when the person sending the agreement fills it before it goes out (the deal's "
    "terms: "
    "purpose, dates, durations, amounts, governing law, choices between options); 'none', when "
    "nobody fills it (decoration, office use). signature, initials and date_signed always name a "
    "role: date_signed names the party whose signing it records, and is filled automatically."
)
MUST_FILL_HELP = (
    "true when the agreement cannot be signed or used without a value: every signature, initials "
    "and date_signed; each party's name; the deal's terms the agreement depends on (dates, "
    "durations, amounts, governing law, a choice between options). For a checkbox, true means it "
    "must be ticked to sign (an 'I agree' or an acknowledgement). false only when the agreement "
    "itself treats it as optional or as a place for additions, e.g. 'list any changes', "
    "'individuals only', a secondary detail such as a job title, or a field that can sensibly be "
    "left blank."
)
LABEL_HELP = (
    "A short name for the field as a person would say it, e.g. 'Governing law: state'. Plain "
    "words: "
    "no links or markup."
)


ANCHOR_MAX = 80  # characters of an extra field's anchor words: what the AI copies, what we search


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Role(Strict):
    """A party that fills or signs, named from the agreement's own word (never a person's name).
    Its display label is derived from the slug: party_1 is shown as 'Party 1'."""

    slug: str = Field(
        pattern=r"^[a-z][a-z0-9_]{0,39}$",
        description=(
            "Lowercase with underscores, from the agreement's own word: client, tenant, "
            "disclosing_party, party_1. A second party of the same kind gets _2, _3: tenant_2."
        ),
    )
    kind: RoleKind = Field(
        description=(
            "signer: the customer side (clients, co-clients, guarantors), who sign first. "
            "countersigner: the side that sends the agreement (the firm, its representative), who "
            "signs last."
        )
    )


class ExtraField(Strict):
    """A blank the agreement asks to be filled or signed where there is no field marker."""

    page: int = Field(description="The page number the blank is on (1-based).")
    anchor_text: str = Field(
        description=(
            "The words printed immediately before the blank, on the same line: its label, such "
            "as 'NAME:' or 'Date of birth:'. Copied exactly from the document, at most "
            f"{ANCHOR_MAX} characters. The blank is the empty space right after these words; when "
            "it is on the line below its label, the label's words."
        )
    )
    holds: Holds = Field(description=HOLDS_HELP)
    format: DateFormat | None = Field(description=FORMAT_HELP)
    filled_by: str = Field(description=FILLED_BY_HELP)
    label: str = Field(description=LABEL_HELP)
    must_fill: bool = Field(description=MUST_FILL_HELP)


class DocumentMeta(Strict):
    """The agreement's name and description, written for every version: the version keeps them, and
    the document takes them while nobody has written its own (Phase 4 §1.3)."""

    name: str = Field(
        description=(
            "At most 120 characters: how a person at the firm would call it, in words with spaces. "
            "Keep the current name when it is already apt; a file name (hyphens, underscores, an "
            "extension) never is."
        )
    )
    description: str = Field(
        description=(
            "Two or three short sentences, at most 300 characters in all, however long the "
            "agreement: what kind of agreement it is and between how many parties (by their "
            "roles); "
            "the main subjects it covers; who signs and whether it is countersigned. Plain words, "
            "no lists, no links. Example: 'A mutual non-disclosure agreement between two parties. "
            "It covers the purpose and term of sharing confidential information, how long it stays "
            "protected, governing law and jurisdiction. Both parties sign; no countersignature.'"
        )
    )


def answer_model(field_ids: list[str]) -> type[BaseModel]:
    """The answer for one document: every field id is an enum of that document's ids."""
    field_id: Any = Literal[tuple(field_ids)]
    dependency = create_model(
        "Dependency",
        __base__=Strict,
        __doc__="The option this field applies under.",
        id=(field_id, Field(description="The id of the radio group, dropdown or checkbox.")),
        option=(
            str,
            Field(
                description=(
                    "The option value under which it applies, as in the marker ⟦f4=Choice1⟧. When "
                    "the id is a checkbox, the value is 'checked'."
                )
            ),
        ),
    )
    field_answer = create_model(
        "FieldAnswer",
        __base__=Strict,
        __doc__="One field from <fields>, answered once.",
        id=(field_id, Field(description="The field's id from <fields>.")),
        holds=(Holds, Field(description=HOLDS_HELP)),
        format=(DateFormat | None, Field(description=FORMAT_HELP)),
        filled_by=(str, Field(description=FILLED_BY_HELP)),
        label=(str, Field(description=LABEL_HELP)),
        must_fill=(bool, Field(description=MUST_FILL_HELP)),
        depends_on=(
            dependency | None,
            Field(
                description=(
                    "When the field only applies if an option is chosen (the blank in 'Expires "
                    "⟦f3⟧ from Effective Date.' applies only when that option is chosen, or a "
                    "condition written in the text such as 'individuals only'): that option. "
                    "Otherwise null."
                )
            ),
        ),
    )
    checkbox_group = create_model(
        "CheckboxGroup",
        __base__=Strict,
        __doc__=(
            "Separate checkboxes that together are one choice where only one may be ticked "
            "('☐ Individual ☐ Business entity', '☐ Yes ☐ No'). Not checkboxes that may each be "
            "ticked independently."
        ),
        ids=(list[field_id], Field(description="The checkbox ids, two or more, in reading order.")),
        label=(str, Field(description="What the choice is about, e.g. 'Recipient type'.")),
    )
    return create_model(
        "FieldAssignment",
        __base__=Strict,
        __doc__="Who fills each field of the agreement, and what it holds.",
        roles=(
            list[Role],
            Field(
                description=(
                    "Every party named in filled_by, each once (and no other); at least one signer."
                )
            ),
        ),
        fields=(list[field_answer], Field(description="Every id in <fields>, exactly once.")),
        checkbox_groups=(
            list[checkbox_group],
            Field(description="Checkboxes that form one choice; empty when there are none."),
        ),
        extra_fields=(
            list[ExtraField],
            Field(description="Blanks with no field marker; empty when there are none."),
        ),
        document=(DocumentMeta, Field(description="This agreement's name and description.")),
    )
