"""The derive stage (Phase 5 LLD topic 4): check the answer, then build the version's fields.

``check`` lists what the schema cannot enforce; those problems go back to the AI once (§3.4).
``derive`` then always produces a storable result: whatever is still wrong is resolved and flagged
for review, never failed (§1.4). The result has one field per key (§5.2): a value given once and
placed everywhere it is asked (signature, initials, signing date, legal name), a checkbox group as
one choice, each listing the field ids it came from. Dependencies point at keys, and the layout's
win over the AI's (§4.2). One pass with hash maps: O(F) for F fields.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Collection
from typing import Any, Literal

import pymupdf
from pydantic import BaseModel, ConfigDict

from signora.modules.detection.geometry import Box
from signora.modules.detection.page_text import UNDERSCORES
from signora.modules.detection.reading import FieldsFrom, FoundField, Reading
from signora.modules.detection.schema import ALLOWED, ANCHOR_MAX
from signora.modules.detection.writing_space import GROWS, DocumentSpace
from signora.modules.review.formats import format_for
from signora.modules.review.keys import name_words, unique
from signora.modules.review.values import LABEL_MAX, OWN, PARTY_VALUES, SENSITIVE, SHARED

NAME_MAX = 120
DESCRIPTION_MAX = 300
TOKEN = re.compile(r"\{(f\d+)(?:=[^{}]*)?\}")
# Links and scripts in what the AI writes (§3.5): personal data is a later feature (Presidio).
UNSAFE_TEXT = re.compile(
    r"https?://|www\.|javascript:|data:|<\s*/?\s*[a-z][^>]*>|\]\s*\(", re.IGNORECASE
)
# Text in a document addressed to an AI (§3.5): flagged for review, nothing blocked.
ADDRESSED_TO_AI = re.compile(
    r"ignore (?:all |the |any )?(?:previous|prior|above|earlier) (?:instructions|rules)"
    r"|disregard (?:all |the |any )?(?:previous|prior|above)?\s*(?:instructions|rules)"
    r"|system prompt|developer message"
    r"|you are (?:now )?(?:an? )?(?:ai|assistant|language model|chatbot)\b"
    r"|as an ai\b",
    re.IGNORECASE,
)
# What a box holds when the AI's answer is not allowed for its kind (a text box or blank: text).
KIND_DEFAULT = {
    "signature": "signature",
    "checkbox": "checkbox",
    "radio": "choice",
    "combobox": "choice",
    "listbox": "choice",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleOut(_Model):
    slug: str
    kind: Literal["signer", "countersigner"]
    label: str
    position: int


class PlacementOut(_Model):
    page: int
    rect: Box
    kind: str  # text, signature, checkbox, radio, combobox, listbox, blank
    pdf_field: str | None = None
    option_value: str | None = None  # a choice: the value this place stands for
    option_text: str | None = None
    options: list[str] | None = None  # a dropdown's or a list's own options, in the PDF's order


class Dependency(_Model):
    key: str
    option: str  # an option's value, or "checked"
    source: Literal["layout", "ai"]


class FieldOut(_Model):
    key: str
    label: str
    holds: str
    format: str | None = None  # how a date or a part of one is written (7c)
    filled_by: Literal["role", "sender", "none"]
    role: str | None  # the role's slug when filled_by is "role"
    required: bool
    sensitive: bool
    depends_on: Dependency | None = None
    needs_review: str | None = None
    ids: list[str]  # the field ids it came from (f6, f8, …)
    placements: list[PlacementOut]


class NotAsked(_Model):
    id: str
    pdf_field: str | None
    kind: str
    why: list[str]


class Flags(_Model):
    no_fields: bool = False
    addressed_to_ai: bool = False
    repaired: bool = False
    xfa: bool = False
    already_signed: bool = False
    name_dropped: bool = False


class DocumentOut(_Model):
    name: str | None
    description: str | None


class Result(_Model):
    fields_from: FieldsFrom
    roles: list[RoleOut]
    fields: list[FieldOut]
    not_asked: list[NotAsked]
    document: DocumentOut | None
    flags: Flags
    notes: list[str]


def _fit(text: str, limit: int) -> str:
    """Text within ``limit`` characters: as it is, else cut after its last whole sentence that
    fits (a description of two or three sentences keeps the ones it can), else nothing. A model
    counts characters loosely: 302 for at most 300 was seen twice in eight runs."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    ends = [head.rfind(mark) for mark in (". ", "! ", "? ")] + [
        limit - 1 if head[-1:] in ".!?" else -1
    ]
    end = max(ends)
    return head[: end + 1].strip() if end > 0 else ""


def role_label(slug: str, text: str = "") -> str:
    """A party's label as the document prints it: the most common printing of the slug's words
    that starts with a capital and is not all capitals ("UL Lafayette", "Disclosing Party"), so
    a heading in capitals or the words inside a sentence do not decide it. Without one, the
    slug's words capitalised: party_1 → 'Party 1'. O(T) for T characters of text."""
    words = slug.split("_")
    pattern = re.compile(
        r"(?<![\w])" + r"[\s\-]+".join(re.escape(word) for word in words) + r"(?![\w])",
        re.IGNORECASE,
    )
    printed = Counter(
        " ".join(found.group(0).split())
        for found in pattern.finditer(text)
        if found.group(0)[0].isupper() and not found.group(0).isupper()
    )
    if printed:
        return printed.most_common(1)[0][0]
    return " ".join(part.capitalize() for part in words)


def _document_text(reading: Reading) -> str:
    """Everything the document says, as the AI receives it: its page text and what its fields
    carry (names, tooltips, values, options, option words), whitespace collapsed (the layout
    spaces words into columns). The uploader's instructions are not the document's."""
    parts = [reading.layout]
    for found in reading.fields:
        parts += [found.pdf_field or "", found.tooltip or "", found.value or "", *found.options]
        parts += [placement.option_text or "" for placement in found.placements]
    return " ".join(" ".join(parts).split())


def _unsafe(text: str | None) -> bool:
    return bool(text and UNSAFE_TEXT.search(text))


def layout_dependencies(reading: Reading) -> dict[str, tuple[str, str]]:
    """A field whose marker sits inside an option's words applies under that option: {child id:
    (choice id, option value or "checked")}. From the layout, not the AI."""
    found: dict[str, tuple[str, str]] = {}
    for field in reading.asked:
        if field.kind not in ("radio", "checkbox"):
            continue
        for placement in field.placements:
            option = placement.value if field.kind == "radio" else "checked"
            for child in TOKEN.findall(placement.option_text or ""):
                if child != field.id and option:
                    found.setdefault(child, (field.id, option))
    return found


def _space(reading: Reading, document: pymupdf.Document) -> DocumentSpace:
    """The document's free space, around every place the read stage found."""
    places: dict[int, list[Box]] = {}
    for found in reading.fields:
        for placement in found.placements:
            places.setdefault(placement.page, []).append(placement.rect)
    return DocumentSpace(document, places)


def _party_places(answer: dict[str, Any], reading: Reading, filled_by: str, page: int) -> list[Box]:
    """The places on a page of the found fields the answer gives to ``filled_by``: what decides
    which printing of an extra field's words is that party's (F10). One reading for the check
    and for placing, so the repair round is asked about exactly what placing will refuse. O(F)."""
    theirs = {item["id"] for item in answer["fields"] if item["filled_by"] == filled_by}
    return [
        placement.rect
        for found in reading.asked
        if found.id in theirs
        for placement in found.placements
        if placement.page == page
    ]


def _label_words(extra: dict[str, Any]) -> str:
    """The words an extra field is placed after: its anchor, up to any blank it quotes. An anchor
    that copies the blank itself ("Total: $______") is cut before it, so the quoted blank is
    measured like any space after a label (a field or text already there: no room)."""
    return UNDERSCORES.split(extra["anchor_text"][:ANCHOR_MAX], maxsplit=1)[0].strip()


def _extra_problem(space: DocumentSpace, extra: dict[str, Any], near: list[Box]) -> str | None:
    """Why an extra field cannot be placed from its words, in words; None when it can."""
    words, number = _label_words(extra), extra["page"]
    if not words:
        return "its words are only the blank: give the words printed right before it"
    page = space.page(number)
    if page is None or _unsafe(words) or not page.find(words):
        return f"its words are not on page {number}"
    if space.locate_after(number, words, near) is None:
        if space.field_after(number, words, near):
            return None  # a form field is that blank already: nothing for the AI to fix
        if space.extra_after(number, words, near):
            return "the same blank as another extra field: list it once"
        return (
            f"there is no free space after {words!r} on page {number} where the other fields of "
            f"{extra['filled_by']} are: give the words printed right before the blank, and check "
            "who fills it (a value already printed is not a blank)"
        )
    return None


def _not_the_same(item: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str | None:
    """Why a field's ``same_as`` cannot hold (F11), in words; None when it can or is not given.
    The same value is one party's (or the sender's) and one kind, never a mark (a choice)."""
    same = item.get("same_as")
    if not same:
        return None
    if same == item["id"]:
        return "marked the same value as itself"
    target = by_id.get(same)
    if target is None:
        return f"marked the same value as {same}, which is not a field"
    if target["filled_by"] != item["filled_by"]:
        return f"marked the same value as {same}, but not the same party's"
    if target["holds"] != item["holds"] or item["holds"] in ("checkbox", "choice"):
        return f"marked the same value as {same}, but not the same kind of value"
    return None


def check(answer: dict[str, Any], reading: Reading, document: pymupdf.Document) -> list[str]:
    """What the strict schema cannot enforce (§4.1); each problem in words, for the repair round."""
    problems: list[str] = []
    asked = {field.id: field for field in reading.asked}
    roles = [role["slug"] for role in answer["roles"]]
    if len(set(roles)) != len(roles):
        problems.append(f"role slugs repeat: {roles}")
    if not any(role["kind"] == "signer" for role in answer["roles"]):
        problems.append("no role is a signer")
    counts: dict[str, int] = {}
    for item in answer["fields"]:
        counts[item["id"]] = counts.get(item["id"], 0) + 1
    problems += [f"{i}: answered {counts.get(i, 0)} times" for i in asked if counts.get(i, 0) != 1]
    used = {item["filled_by"] for item in answer["fields"] + answer["extra_fields"]}
    if unused := set(roles) - used:
        problems.append(f"roles that fill nothing: {sorted(unused)}")
    for item in [*answer["fields"], *answer["extra_fields"]]:
        name = item.get("id") or f"extra field {item['label']!r}"
        if item["filled_by"] not in {*roles, "sender", "none"}:
            problems.append(f"{name}: filled_by {item['filled_by']!r} is not a listed role")
        elif item["holds"] in OWN and item["filled_by"] in ("sender", "none"):
            problems.append(f"{name}: a {item['holds']} must be given by a party")
        if _unsafe(item["label"]):
            problems.append(f"{name}: the label has a link or markup")
    by_id = {item["id"]: item for item in answer["fields"]}
    for item in answer["fields"]:
        if (why := _not_the_same(item, by_id)) is not None:
            problems.append(f"{item['id']}: {why}")
    for item in answer["fields"]:
        found = asked.get(item["id"])
        if found and item["holds"] not in ALLOWED.get(found.kind, frozenset()):
            problems.append(f"{item['id']}: a {found.kind} cannot hold {item['holds']}")
        dependency = item["depends_on"]
        if dependency:
            target = asked.get(dependency["id"])
            options = (
                ["checked"]
                if target and target.kind == "checkbox"
                else (target.options if target else [])
            )
            if dependency["option"] not in options:
                problems.append(f"{item['id']}: depends on {dependency}, which is not an option")
    in_groups: dict[str, int] = {}
    for group in answer["checkbox_groups"]:
        if len(group["ids"]) < 2:
            problems.append(f"checkbox group {group['label']!r} has fewer than two checkboxes")
        for member in group["ids"]:
            in_groups[member] = in_groups.get(member, 0) + 1
            if member in asked and asked[member].kind != "checkbox":
                problems.append(
                    f"checkbox group {group['label']!r}: {member} is a {asked[member].kind}"
                )
    problems += [f"{m}: in {n} checkbox groups" for m, n in in_groups.items() if n > 1]
    space = _space(reading, document)
    for extra in answer["extra_fields"]:
        near = _party_places(answer, reading, extra["filled_by"], extra["page"])
        if (problem := _extra_problem(space, extra, near)) is not None:
            problems.append(f"extra field {extra['label']!r}: {problem}")
        else:  # placed as derive will, so a second field on the same blank is seen
            space.place_after(extra["page"], _label_words(extra), near)
    meta = answer["document"]
    if meta:
        if not 1 <= len(meta["name"].strip()) <= NAME_MAX:
            problems.append(f"the name has {len(meta['name'])} characters (1-{NAME_MAX})")
        if len(meta["description"]) > DESCRIPTION_MAX:
            problems.append(
                f"the description has {len(meta['description'])} characters "
                f"(at most {DESCRIPTION_MAX})"
            )
        if _unsafe(meta["name"]) or _unsafe(meta["description"]):
            problems.append("the name or description has a link or markup")
    return problems


class _Item:
    """One answered place before keys: a found field or an extra field, with what the AI said."""

    def __init__(
        self,
        *,
        ids: list[str],
        label: str,
        holds: str,
        filled_by: str,
        required: bool,
        placements: list[PlacementOut],
        order: tuple[int, float, float],
        review: list[str],
        format: str | None = None,
    ) -> None:
        self.ids, self.label, self.holds, self.filled_by = ids, label, holds, filled_by
        self.required, self.placements, self.order, self.review = (
            required,
            placements,
            order,
            review,
        )
        self.format = format_for(holds, format)  # the AI's, when its type has it (7c)
        self.group: int | None = None  # the checkbox group it is one option of, by number
        self.group_label: str | None = None
        self.depends: tuple[str, str, Literal["layout", "ai"]] | None = None
        self.same: _Item | None = None  # the earliest field of the value it is one place of (F11)


def _placements(found: FoundField) -> list[PlacementOut]:
    return [
        PlacementOut(
            page=p.page,
            rect=p.rect,
            kind=found.kind,
            pdf_field=p.pdf_field,
            option_value=p.value if found.kind == "radio" else None,
            option_text=p.option_text,
            options=list(found.options) if found.kind in ("combobox", "listbox") else None,
        )
        for p in found.placements
    ]


def _who_fills(holds: str, filled_by: str, roles: Collection[str]) -> str:
    """Who fills a field, kept to the rules for every field, found or extra (§4.1): a party the
    answer listed, the sender or nobody; and a party's own value (a signature, initials, a
    signing date…) only ever that party, so "the sender" or nobody becomes nobody, for review."""
    if filled_by not in {*roles, "sender", "none"}:
        return "none"
    if holds in OWN and filled_by in ("sender", "none"):
        return "none"
    return filled_by


def derive(
    reading: Reading,
    answer: dict[str, Any],
    document: pymupdf.Document,
    *,
    problems: list[str],
    repaired: bool,
) -> Result:
    """A storable result whatever the answer: problems still there are resolved and flagged."""
    asked = {field.id: field for field in reading.asked}
    notes: list[str] = []
    listed = {role["slug"]: role["kind"] for role in answer["roles"]}
    answered = {item["id"]: item for item in answer["fields"] if item["id"] in asked}
    by_id_problems: dict[str, list[str]] = {}
    for problem in problems:
        head = problem.split(":", 1)[0]
        if head in asked:
            by_id_problems.setdefault(head, []).append(problem.split(":", 1)[1].strip())
    layout = layout_dependencies(reading)

    items: dict[str, _Item] = {}
    for found in reading.asked:
        item = answered.get(found.id)
        if found.drawn and item is not None and item["filled_by"] == "none":
            # A drawn line is the least certain mark (F1): the AI read it in its sentence and
            # says nobody fills it, so it is decoration, not a field.
            notes.append(f"{found.id}: a drawn line nobody fills: not kept as a field")
            continue
        if item is None:
            review = ["not assigned to anyone"]  # rather than "answered 0 times"
            holds, filled_by, label, required = (
                KIND_DEFAULT.get(found.kind, "text"),
                "none",
                found.label or found.id,
                False,
            )
        else:
            review = list(by_id_problems.get(found.id, []))
            holds, filled_by, label, required = (
                item["holds"],
                item["filled_by"],
                item["label"],
                item["must_fill"],
            )
            if holds not in ALLOWED.get(found.kind, frozenset()):
                holds = KIND_DEFAULT.get(found.kind, "text")
            filled_by = _who_fills(holds, filled_by, listed)
            if _unsafe(label):
                label = found.label or found.id
        if label == found.id:  # nothing names it: neither the page nor the AI (F4)
            review.append("nothing on the page names it: check what it asks")
        review += [issue for issue in found.issues if issue.startswith("page ")]  # its box (F4)
        first = found.placements[0]
        entry = _Item(
            ids=[found.id],
            label=label[:LABEL_MAX],
            holds=holds,
            filled_by=filled_by,
            required=required,
            placements=_placements(found),
            order=(first.page, first.rect[1], first.rect[0]),
            review=review,
            format=item.get("format") if item else None,
        )
        if found.id in layout:
            parent, option = layout[found.id]
            entry.depends = (parent, option, "layout")
            ai = item["depends_on"] if item else None
            if ai and (ai["id"], ai["option"]) != (parent, option):
                notes.append(
                    f"{found.id}: the AI said {ai['id']}={ai['option']}; "
                    f"the layout's {parent}={option} is used"
                )
        elif item and item["depends_on"]:
            target = asked.get(item["depends_on"]["id"])
            options = (
                ["checked"]
                if target and target.kind == "checkbox"
                else (target.options if target else [])
            )
            if item["depends_on"]["option"] in options:
                entry.depends = (item["depends_on"]["id"], item["depends_on"]["option"], "ai")
        items[found.id] = entry

    # Extra fields (F10): each goes in the free space after the words printed before it, at the
    # printing of those words nearest the same party's other places on its page, or nowhere.
    space = _space(reading, document)
    for number, extra in enumerate(answer["extra_fields"], start=1):
        holds = extra["holds"] if extra["holds"] not in ("checkbox", "choice") else "text"
        filled_by = _who_fills(holds, extra["filled_by"], listed)
        near = _party_places(answer, reading, extra["filled_by"], extra["page"])
        why = _extra_problem(space, extra, near)
        rect = (
            None if why is not None else space.place_after(extra["page"], _label_words(extra), near)
        )
        if rect is None:
            why = why or "a form field already sits after its words: that field is the blank"
            notes.append(f"extra field {extra['label']!r} dropped: {why}")
            continue
        items[f"x{number}"] = _Item(
            ids=[],
            label=extra["label"][:LABEL_MAX]
            if not _unsafe(extra["label"])
            else extra["anchor_text"][:LABEL_MAX],
            holds=holds,
            filled_by=filled_by,
            required=extra["must_fill"],
            placements=[PlacementOut(page=extra["page"], rect=rect, kind="blank")],
            order=(extra["page"], rect[1], rect[0]),
            review=["placed after the words printed before it: check its position"],
            format=extra.get("format"),
        )

    _room_to_sign(items, space)
    _same_values(answer, items, notes)

    # Checkbox groups: one choice, its options the checkboxes (§4.3). Each group is its own
    # choice, by number: two groups may well share a label ("Yes or no" asked twice).
    for number, group in enumerate(answer["checkbox_groups"]):
        members = [
            m for m in group["ids"] if m in items and asked.get(m) and asked[m].kind == "checkbox"
        ]
        if len(members) < 2 or any(items[m].group is not None for m in members):
            notes.append(f"checkbox group {group['label']!r} not used")
            continue
        for member in members:
            items[member].group, items[member].group_label = number, group["label"][:LABEL_MAX]

    fields = _keyed(items)
    # Roles in signing order: signers by where they first appear, then countersigners (§4.5).
    # From the fields as stored, so a party whose only boxes merged into another's fills nothing.
    first_seen: dict[str, int] = {}
    for position, field in enumerate(fields):
        if field.role is not None:
            first_seen.setdefault(field.role, position)
    order = sorted(first_seen, key=lambda slug: (listed[slug] != "signer", first_seen[slug]))
    roles = [
        RoleOut(slug=slug, kind=listed[slug], label=role_label(slug, reading.layout), position=n)
        for n, slug in enumerate(order, start=1)
    ]
    dropped = set(listed) - set(first_seen)
    if dropped:
        notes.append(f"roles that fill nothing dropped: {sorted(dropped)}")
    if reading.asked and not fields:
        notes.append("nothing to store")
    meta = answer["document"]
    document_out = None
    name_dropped = False
    if meta is not None:
        name = meta["name"].strip()
        description = meta["description"].strip()
        if _unsafe(name) or not 1 <= len(name) <= NAME_MAX:
            name, name_dropped = "", True
        description = "" if _unsafe(description) else _fit(description, DESCRIPTION_MAX)
        name_dropped = name_dropped or (not description and bool(meta["description"].strip()))
        document_out = DocumentOut(name=name or None, description=description or None)
    return Result(
        fields_from=reading.fields_from,
        roles=roles,
        fields=fields,
        not_asked=[
            NotAsked(id=f.id, pdf_field=f.pdf_field, kind=f.kind, why=f.issues)
            for f in reading.fields
            if not f.fillable
        ],
        document=document_out,
        flags=Flags(
            no_fields=not fields,
            addressed_to_ai=bool(ADDRESSED_TO_AI.search(_document_text(reading))),
            repaired=repaired,
            xfa=reading.xfa,
            already_signed=reading.already_signed,
            name_dropped=name_dropped,
        ),
        notes=notes,
    )


def _room_to_sign(items: dict[str, _Item], space: DocumentSpace) -> None:
    """A signature or initials on a blank line takes the writing space above the line (findings
    F2); a form field's box stays as its author drew it. The space holds every field's original
    place (and the extra fields' places once taken), so one grown box never limits another.
    O(W + P) per page that holds such a line, for W words and P places."""
    for item in items.values():
        if item.holds not in GROWS:
            continue
        for index, place in enumerate(item.placements):
            page = space.page(place.page) if place.kind == "blank" else None
            if page is not None:
                item.placements[index] = place.model_copy(
                    update={"rect": page.room_above(place.rect)}
                )


def _reading_order(items: dict[str, _Item]) -> list[_Item]:
    """The fields in reading order, ties kept as answered: the one order keys are made in, so
    a value's first field (``_same_values``) is always keyed before its other places."""
    return sorted(items.values(), key=lambda item: item.order)


def _same_values(answer: dict[str, Any], items: dict[str, _Item], notes: list[str]) -> None:
    """Fields the AI marks as one value (F11) become one key: each mark that holds (the same
    party's, the same kind, as stored) joins its two fields; a group's earliest field gives the
    key. A mark that does not hold is kept apart, with a note. Union-find, near-linear: O(F)."""
    parent: dict[str, str] = {}

    def root(field_id: str) -> str:
        while parent.get(field_id, field_id) != field_id:
            parent[field_id] = parent.get(parent[field_id], parent[field_id])
            field_id = parent[field_id]
        return field_id

    by_id = {item["id"]: item for item in answer["fields"]}
    for item in answer["fields"]:
        same = item.get("same_as")
        if not same:
            continue
        why = _not_the_same(item, by_id)
        mine, theirs = items.get(item["id"]), items.get(same)
        if why is None and mine and theirs:
            stored_apart = (mine.filled_by, mine.holds) != (theirs.filled_by, theirs.holds)
            why = "not the same once checked" if stored_apart else None
        if why is not None or mine is None or theirs is None:
            notes.append(f"{item['id']}: kept apart from {same}: not the same value ({why})")
            continue
        parent[root(item["id"])] = root(same)
    rank = {id(item): n for n, item in enumerate(_reading_order(items))}
    groups: dict[str, list[_Item]] = {}
    for field_id in parent:
        groups.setdefault(root(field_id), []).append(items[field_id])
    for field_id, members in groups.items():
        everyone = {id(item): item for item in [items[field_id], *members]}.values()
        first = min(everyone, key=lambda item: rank[id(item)])  # as _keyed will key them
        for item in everyone:
            if item is not first:
                item.same = first


def _owner(item: _Item) -> tuple[str, str | None]:
    """(``filled_by`` as stored, the role's slug)."""
    if item.filled_by in ("sender", "none"):
        return item.filled_by, None
    return "role", item.filled_by


def _option_value(item: _Item, placement: PlacementOut) -> str:
    """What a checkbox in a group stands for as an option: its own words, else the AI's label."""
    return placement.option_text or item.label


def _keyed(items: dict[str, _Item]) -> list[FieldOut]:
    """One field per key, in reading order: shared values and checkbox groups merged (§4.3)."""
    ordered = _reading_order(items)
    key_of: dict[int, str] = {}
    taken: set[str] = set()
    shared: dict[str, str] = {}  # (role, holds) -> key for values given once
    groups: dict[int, str] = {}
    for item in ordered:
        _, role = _owner(item)
        owner = role or "agreement"
        if item.same is not None:  # one value with an earlier field (F11): its key
            key_of[id(item)] = key_of[id(item.same)]
        elif item.group is not None:
            if item.group not in groups:
                words = name_words(item.group_label or "choice", role)
                groups[item.group] = unique(f"{owner}.{words}", taken)
            key_of[id(item)] = groups[item.group]
        elif role and item.holds in SHARED:
            share = f"{role}.{item.holds}"
            if share not in shared:
                shared[share] = unique(share, taken)
            key_of[id(item)] = shared[share]
        elif role and item.holds in PARTY_VALUES:
            key_of[id(item)] = unique(f"{role}.{item.holds}", taken)
        else:
            key_of[id(item)] = unique(f"{owner}.{name_words(item.label, role)}", taken)
    key_by_id = {i: key_of[id(item)] for item in ordered for i in item.ids}
    item_by_id = {i: item for item in ordered for i in item.ids}

    fields: dict[str, FieldOut] = {}
    disagree: set[str] = set()  # keys whose places' conditions differ: noted once
    for item in ordered:
        key = key_of[id(item)]
        filled_by, role = _owner(item)
        placements = list(item.placements)
        if item.group is not None:
            placements = [
                p.model_copy(update={"option_value": _option_value(item, p)}) for p in placements
            ]
        dependency = None
        if item.depends is not None:
            parent, option, source = item.depends
            parent_key = key_by_id.get(parent)
            if parent_key is not None and parent_key != key:
                parent_item = item_by_id[parent]
                if parent_item.group is not None and option == "checked":
                    # A checkbox in a group: the choice of that option, named as its placement is.
                    option = _option_value(parent_item, parent_item.placements[0])
                dependency = Dependency(key=parent_key, option=option, source=source)
        existing = fields.get(key)
        if existing is None:
            fields[key] = FieldOut(
                key=key,
                label=item.group_label or item.label,
                holds="choice" if item.group is not None else item.holds,
                format=None if item.group is not None else item.format,
                filled_by=filled_by,  # type: ignore[arg-type]
                role=role,
                required=item.required,
                sensitive=item.holds in SENSITIVE,
                depends_on=dependency,
                needs_review="; ".join(item.review) or None,
                ids=list(item.ids),
                placements=placements,
            )
            continue
        existing.ids.extend(item.ids)
        existing.placements.extend(placements)
        existing.required = existing.required or item.required
        if item.review:
            existing.needs_review = "; ".join(filter(None, [existing.needs_review, *item.review]))
        if dependency != existing.depends_on and key not in disagree:
            # One value in many places, not all under the same option (initials on every page,
            # one of them in an optional addendum): a field applies as a whole, so it applies
            # always, and a person decides.
            disagree.add(key)
            existing.depends_on = None
            note = "its places do not all apply under the same option; check when it applies"
            existing.needs_review = "; ".join(filter(None, [existing.needs_review, note]))
    _break_loops(fields)
    _keep_conditions_with_one_filler(fields)
    return list(fields.values())


def _keep_conditions_with_one_filler(fields: dict[str, FieldOut]) -> None:
    """A field applies under an option of a field the same person fills (review refuses any other:
    whoever fills a field must be the one who answers what it depends on). Where the proposal
    has two people, the condition is dropped and the field needs a look. O(F)."""
    for field in fields.values():
        parent = fields.get(field.depends_on.key) if field.depends_on is not None else None
        if parent is None or (parent.filled_by, parent.role) == (field.filled_by, field.role):
            continue
        field.depends_on = None
        note = "its condition was on a field someone else fills; check when it applies"
        field.needs_review = "; ".join(filter(None, [field.needs_review, note]))


def _break_loops(fields: dict[str, FieldOut]) -> None:
    """Dependencies form a forest: a field that applies under an option of another, never in a
    loop (two fields each shown only when the other is filled could never be shown, and a list
    of them as a tree would lose both). Each chain is walked once, so O(F): where one closes a
    loop, the AI's link in it is dropped (the layout's are facts), else the last, and that field
    needs a look."""
    visiting, done = 1, 2
    state: dict[str, int] = {}
    for start in fields:
        path: list[str] = []
        key: str | None = start
        while key is not None and key not in state:
            state[key] = visiting
            path.append(key)
            dependency = fields[key].depends_on
            key = dependency.key if dependency is not None and dependency.key in fields else None
        if key is not None and state[key] == visiting:
            loop = path[path.index(key) :]
            cut = next(
                (k for k in loop if (d := fields[k].depends_on) is not None and d.source == "ai"),
                loop[-1],
            )
            field = fields[cut]
            field.depends_on = None
            note = "its condition depended on itself in a loop; check when it applies"
            field.needs_review = "; ".join(filter(None, [field.needs_review, note]))
        for key_on_path in path:
            state[key_on_path] = done
