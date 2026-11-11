"""What the read stage finds in a document (Phase 5 LLD topic 2).

The form fields and blanks of a document, numbered ``f1, f2, …`` in reading order, with the layout
text the AI reads (``read.read_document`` builds it). Saved as JSON (``detection_runs.parsed``) and
read back when a run resumes, so these are Pydantic models.

Positions are PDF points, origin top-left, on the page **as displayed** (its rotation applied).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from signora.modules.detection.geometry import Box

FieldKind = Literal[
    "text",
    "signature",
    "checkbox",
    "radio",
    "combobox",
    "listbox",
    "push_button",
    "unknown",
    "blank",
]
FieldsFrom = Literal["form_fields", "blanks", "none"]
TOKEN = re.compile(r"\{([^{}=]+)(=[^{}]*)?\}")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Placement(_Model):
    """One place a field appears: a widget, one option of a radio group, or a blank."""

    page: int
    rect: Box
    pdf_field: str | None = None  # the form field signing fills; None for a blank
    value: str | None = None  # the value this place sets (a radio option, a checkbox's "on")
    option_text: str | None = None  # an option's own words, other fields in it as {f3}
    hidden: bool = False
    continued: list[Box] = []  # the rest of a placeholder that wraps onto the next lines


class FoundField(_Model):
    id: str = ""  # f1, f2, … in reading order: the handle the AI answers with
    ref: str  # internal handle until ids exist: "form:<name>" or "blank:<page>:<n>"
    kind: FieldKind
    pdf_field: str | None = None
    placements: list[Placement]
    tooltip: str | None = None  # the form author's own description (/TU)
    label_left: str | None = None
    label_above: str | None = None
    label_below: str | None = None
    text_inside: str | None = None  # words drawn in its box (often its own appearance)
    value: str | None = None
    sample_value: bool = False  # a bracketed value a template ships with ("[Fill in state]")
    drawn: bool = False  # a blank from a line drawn as a graphic, not marked in the text (F1)
    options: list[str] = []  # dropdown and list choices; a radio group's option values
    required: bool = False
    read_only: bool = False
    multiline: bool = False
    max_length: int | None = None
    text_format: str | None = None  # date, time, number, percent, special (from the PDF)
    multi_select: bool = False
    signed: bool = False
    calculated: bool = False  # a total the PDF computes from other fields
    issues: list[str] = []

    @property
    def fillable(self) -> bool:
        """Whether a person could be asked for it (the rest stay as they are in the PDF)."""
        never = (
            self.read_only
            or self.signed
            or self.calculated
            or self.kind in ("push_button", "unknown")
        )
        return not never and any(not placement.hidden for placement in self.placements)

    @property
    def label(self) -> str | None:
        return self.tooltip or self.label_left or self.label_above or self.label_below


class PageInfo(_Model):
    number: int
    width: float
    height: float
    rotation: int


class Reading(_Model):
    fields_from: FieldsFrom
    fields: list[FoundField]
    pages: list[PageInfo]
    xfa: bool = False  # what Acrobat shows may differ from these form fields
    already_signed: bool = False  # filling the file breaks that signature
    layout: str = ""  # the document as the AI reads it (§2.5)

    @property
    def asked(self) -> list[FoundField]:
        return [field for field in self.fields if field.fillable]


def number_fields(fields: list[FoundField]) -> list[FoundField]:
    """Ids in reading order (page, row, left to right), and option text written with them."""
    ordered = sorted(
        fields,
        key=lambda f: (
            f.placements[0].page,
            round(f.placements[0].rect[1]),
            f.placements[0].rect[0],
        ),
    )
    ids = {field.ref: f"f{number}" for number, field in enumerate(ordered, start=1)}
    numbered = []
    for field in ordered:
        placements = [
            placement.model_copy(update={"option_text": _with_ids(placement.option_text, ids)})
            for placement in field.placements
        ]
        numbered.append(field.model_copy(update={"id": ids[field.ref], "placements": placements}))
    return numbered


def _with_ids(text: str | None, ids: dict[str, str]) -> str | None:
    if text is None:
        return None
    return TOKEN.sub(
        lambda m: "{" + ids.get(m.group(1), m.group(1)) + (m.group(2) or "") + "}", text
    )
