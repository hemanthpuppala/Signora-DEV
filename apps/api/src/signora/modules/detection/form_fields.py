"""A PDF's own form fields (AcroForm): exact positions, kinds, options, labels (LLD §2.3).

A fillable PDF already says where each field is and what kind it is, so nothing here guesses a
position. Form scripts (formats, calculations) are read as text and never run. Labels are matched in
the page's unrotated space; positions are reported as displayed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from signora.modules.detection.geometry import Box, cut, same_row, union
from signora.modules.detection.page_text import Marked, PageText, pages
from signora.modules.detection.reading import FieldKind, FoundField, PageInfo, Placement

KINDS: dict[int, FieldKind] = {
    pymupdf.PDF_WIDGET_TYPE_TEXT: "text",  # type: ignore[attr-defined]
    pymupdf.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",  # type: ignore[attr-defined]
    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",  # type: ignore[attr-defined]
    pymupdf.PDF_WIDGET_TYPE_COMBOBOX: "combobox",  # type: ignore[attr-defined]
    pymupdf.PDF_WIDGET_TYPE_LISTBOX: "listbox",  # type: ignore[attr-defined]
    pymupdf.PDF_WIDGET_TYPE_SIGNATURE: "signature",  # type: ignore[attr-defined]
    pymupdf.PDF_WIDGET_TYPE_BUTTON: "push_button",  # type: ignore[attr-defined]
}
TEXT_FORMATS = {
    pymupdf.PDF_WIDGET_TX_FORMAT_NUMBER: "number",  # type: ignore[attr-defined]
    pymupdf.PDF_WIDGET_TX_FORMAT_SPECIAL: "special",  # type: ignore[attr-defined]
    pymupdf.PDF_WIDGET_TX_FORMAT_DATE: "date",  # type: ignore[attr-defined]
    pymupdf.PDF_WIDGET_TX_FORMAT_TIME: "time",  # type: ignore[attr-defined]
}
SCRIPT_FORMATS = (
    ("AFDate", "date"),
    ("AFTime", "time"),
    ("AFNumber", "number"),
    ("AFPercent", "percent"),
    ("AFSpecial", "special"),
)
REQUIRED = 1 << 1  # field flags (/Ff), PDF 32000 §12.7.3.1
READ_ONLY = 1 << 0
MULTILINE = 1 << 12
MULTI_SELECT = 1 << 21
HIDDEN = (1 << 1) | (1 << 5)  # annotation flags (/F): Hidden, NoView
SAMPLE_VALUE = re.compile(r"^\s*(\[[^\]]*\]|\{\{[^}]*\}\}|<<[^>]*>>|«[^»]*»|_{3,})\s*$")
PARENT_DEPTH = 16  # parent chains are short; the bound stops a loop in a malicious file
TEXT_MAX = 160
OPTION_TEXT_MAX = 400


@dataclass
class FormRead:
    fields: list[FoundField]
    xfa: bool
    boxes_by_page: dict[int, list[Box]] = field(default_factory=dict)  # unrotated widget boxes


def _key(document: pymupdf.Document, xref: int, key: str) -> tuple[str, str]:
    """A key of the field a widget belongs to: on the widget, else inherited from its parents."""
    for _ in range(PARENT_DEPTH):
        kind, value = document.xref_get_key(xref, key)
        if kind != "null":
            return kind, value
        parent_kind, parent = document.xref_get_key(xref, "Parent")
        if parent_kind != "xref":
            break
        xref = int(parent.split()[0])
    return "null", "null"


def _has_xfa(document: pymupdf.Document) -> bool:
    kind, value = document.xref_get_key(document.pdf_catalog(), "AcroForm")
    if kind == "xref":
        return bool(document.xref_get_key(int(value.split()[0]), "XFA")[0] != "null")
    return bool(kind == "dict" and "/XFA" in value)


def _action_script(document: pymupdf.Document, xref: int, trigger: str) -> str | None:
    """The script of an additional action (``AA/<trigger>/JS``), as text. Never run."""
    kind, value = _key(document, xref, "AA")
    if kind == "xref":
        kind, value = document.xref_get_key(int(value.split()[0]), f"{trigger}/JS")
    elif kind == "dict":
        match = re.search(
            rf"/{trigger}\s*<<.*?/JS\s*(\((?:\\.|[^\\)])*\)|\d+ 0 R)", value, re.DOTALL
        )
        if match is None:
            return None
        raw = match.group(1)
        kind, value = ("xref", raw) if raw.endswith("R") else ("string", raw[1:-1])
    else:
        return None
    if kind == "xref":
        stream = document.xref_stream(int(value.split()[0]))
        return stream.decode("latin-1") if stream else None
    if kind == "string":
        return re.sub(r"\\(.)", r"\1", value)
    return None


def _calculated(document: pymupdf.Document, xref: int) -> bool:
    kind, value = _key(document, xref, "AA")
    if kind == "xref":
        return bool(document.xref_get_key(int(value.split()[0]), "C")[0] != "null")
    return kind == "dict" and re.search(r"/C\s*<<|/C\s+\d+ 0 R", value) is not None


def _text_format(widget: pymupdf.Widget, document: pymupdf.Document) -> str | None:
    known = TEXT_FORMATS.get(widget.text_format)
    if known:
        return known
    script = widget.script_format or _action_script(document, widget.xref, "F")
    if script:
        return next((kind for marker, kind in SCRIPT_FORMATS if marker in script), None)
    return None


def _displayed(page: pymupdf.Page, rect: pymupdf.Rect) -> Box:
    shown = rect * page.rotation_matrix
    shown.normalize()
    return (round(shown.x0, 1), round(shown.y0, 1), round(shown.x1, 1), round(shown.y1, 1))


def _choice(choice: object) -> str:
    """A dropdown choice is a value or an (export value, shown text) pair."""
    if isinstance(choice, (list, tuple)) and len(choice) == 2:
        return f"{choice[1]} ({choice[0]})"
    return str(choice)


def _option_region(
    position: int, refs: list[str], kinds: list[FieldKind], boxes: list[Box], width: float
) -> Box:
    """Where an option's words are: to its right, up to the next option of its group on the row
    (or the page edge), and down to the next option of the group stacked below it."""
    box = boxes[position]
    group = [b for i, b in enumerate(boxes) if i != position and refs[i] == refs[position]]
    toggles = (
        group
        if kinds[position] == "radio"
        else [b for i, b in enumerate(boxes) if i != position and kinds[i] == "checkbox"]
    )
    on_row = [b[0] for b in toggles if same_row(b, box) and b[0] > box[2]]
    below = [b[1] for b in group if b[1] > box[3] - 2 and min(b[2], box[2]) - max(b[0], box[0]) > 0]
    return (
        box[2],
        box[1] - 3,
        min(on_row) - 1 if on_row else width,
        min(below) - 1 if below else box[3] + 3,
    )


def read_form(document: pymupdf.Document) -> FormRead:
    """Every form field, once per name: a name on several pages is one field with several places;
    a radio group is one field with a place per option."""
    by_ref: dict[str, FoundField] = {}
    boxes_by_page: dict[int, list[Box]] = {}
    for number, page in pages(document):
        widgets = list(page.widgets() or [])
        if not widgets:
            continue
        boxes: list[Box] = [tuple(w.rect) for w in widgets]
        boxes_by_page[number] = boxes
        refs = [f"form:{w.field_name or f'xref {w.xref}'}" for w in widgets]
        kinds = [KINDS.get(w.field_type, "unknown") for w in widgets]
        values = [
            (w.on_state() or None) if kind in ("radio", "checkbox") else None
            for w, kind in zip(widgets, kinds, strict=True)
        ]
        text = PageText(
            page,
            [
                Marked(ref, value if kind == "radio" else None, box)
                for ref, value, kind, box in zip(refs, values, kinds, boxes, strict=True)
            ],
        )
        for position, widget in enumerate(widgets):
            ref, kind, box, value = (
                refs[position],
                kinds[position],
                boxes[position],
                values[position],
            )
            option_text = None
            if kind in ("radio", "checkbox"):
                region = _option_region(position, refs, kinds, boxes, page.mediabox.width)
                option_text = cut(text.compose(region, skip=ref), OPTION_TEXT_MAX)
            flags_kind, flags_value = document.xref_get_key(widget.xref, "F")
            annotation = int(flags_value) if flags_kind == "int" else 0
            placement = Placement(
                page=number,
                rect=_displayed(page, widget.rect),
                pdf_field=widget.field_name,
                value=value,
                option_text=option_text,
                hidden=bool(annotation & HIDDEN),
            )
            known = by_ref.get(ref)
            if known is not None:
                known.placements.append(placement)
                if kind == "radio" and value and value not in known.options:
                    known.options.append(value)
                continue
            flags = widget.field_flags or 0
            raw = widget.field_value
            current = None if raw in (None, "", "Off", False) else str(raw)
            found = FoundField(
                ref=ref,
                kind=kind,
                pdf_field=widget.field_name,
                placements=[placement],
                tooltip=cut(widget.field_label, TEXT_MAX)
                if widget.field_label and widget.field_label != widget.field_name
                else None,
                label_left=cut(text.left(box), TEXT_MAX),
                label_above=cut(text.above(box), TEXT_MAX),
                label_below=cut(text.below(box), TEXT_MAX) if kind == "signature" else None,
                text_inside=cut(text.within(position), TEXT_MAX),
                value=cut(current, TEXT_MAX),
                sample_value=bool(current and SAMPLE_VALUE.match(current)),
                required=bool(flags & REQUIRED),
                read_only=bool(flags & READ_ONLY),
            )
            if kind == "text":
                found.multiline = bool(flags & MULTILINE)
                found.max_length = widget.text_maxlen or None
                found.text_format = _text_format(widget, document)
                found.calculated = _calculated(document, widget.xref)
            elif kind in ("combobox", "listbox"):
                found.options = [_choice(choice) for choice in widget.choice_values or []]
                found.multi_select = bool(flags & MULTI_SELECT)
            elif kind == "radio" and value:
                found.options = [value]
            elif kind == "signature":
                found.signed = _key(document, widget.xref, "V")[0] != "null"
            by_ref[ref] = found
        # A radio group is labelled beside the whole group, not beside its first option.
        for ref in {r for r, k in zip(refs, kinds, strict=True) if k == "radio"}:
            group = union(b for r, b in zip(refs, boxes, strict=True) if r == ref)
            by_ref[ref].label_left = cut(text.left(group), TEXT_MAX) or by_ref[ref].label_left
    return FormRead(
        fields=list(by_ref.values()), xfa=_has_xfa(document), boxes_by_page=boxes_by_page
    )


def issues(found: FoundField, pages: list[PageInfo]) -> list[str]:
    """What a person should know about a field, in words (review shows them)."""
    notes = []
    if found.kind == "push_button":
        notes.append("a button, not a value: ignored")
    if found.kind == "unknown":
        notes.append("an unknown kind of field: ignored")
    if found.read_only:
        notes.append("read-only in the PDF: kept as it is, never asked for")
    if found.calculated:
        notes.append("calculated by the PDF from other fields: never asked for")
    if found.signed:
        notes.append("already signed: kept as it is")
    if all(placement.hidden for placement in found.placements):
        notes.append("hidden: never asked for")
    for placement in found.placements:
        x0, y0, x1, y1 = placement.rect
        page = pages[placement.page - 1]
        if x1 - x0 < 1 or y1 - y0 < 1:
            notes.append(f"page {placement.page}: a box with no size")
        elif x1 < 0 or y1 < 0 or x0 > page.width or y0 > page.height:
            notes.append(f"page {placement.page}: a box outside the page")
    if found.kind == "radio":
        if any(placement.option_text is None for placement in found.placements):
            notes.append("an option has no words next to it")
        values = [placement.value for placement in found.placements]
        if len(set(values)) < len(values):
            notes.append("options share a value: the choice is kept by position")
    if found.sample_value:
        notes.append("holds a sample value to replace")
    if found.kind in ("text", "combobox", "listbox", "signature", "blank") and not found.label:
        notes.append("no label found")
    return notes
