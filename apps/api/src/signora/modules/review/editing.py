"""Checking, settling and comparing a saved set (Phase 6 LLD §10.5, §11). Pure: no database.

Each step is one pass over the set with maps by id: O(R + F + P) for R parties, F fields and
P places.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from signora.kernel.errors import FieldError
from signora.modules.review.fieldset import MAX_PLACES, MIN_SIDE, FieldIn, FieldSet, PartyIn
from signora.modules.review.keys import name_words, slug, unique
from signora.modules.review.values import MANUAL_ALLOWED, PARTY_VALUES, SENSITIVE, SHARED

EDGE_TOLERANCE = 0.5  # points: a box may touch its page's edge
CHANGES_KEPT = 200  # the audit entry lists at most this many changes, then counts the rest


@dataclass(frozen=True)
class StoredParty:
    id: uuid.UUID
    label: str
    kind: str
    kind_label: str | None
    position: int


@dataclass(frozen=True)
class StoredPlace:
    id: uuid.UUID
    field_id: uuid.UUID
    page: int
    rect: tuple[float, float, float, float]
    kind: str
    pdf_field: str | None
    option_value: str | None
    option_text: str | None


@dataclass(frozen=True)
class StoredField:
    id: uuid.UUID
    label: str
    holds: str
    holds_label: str | None
    filled_by: str
    party_id: uuid.UUID | None
    required: bool
    sensitive: bool
    depends_on: tuple[uuid.UUID, str] | None
    needs_review: str | None
    origin: str


@dataclass(frozen=True)
class Stored:
    parties: dict[uuid.UUID, StoredParty]
    fields: dict[uuid.UUID, StoredField]
    places: dict[uuid.UUID, StoredPlace]
    _by_field: dict[uuid.UUID, dict[uuid.UUID, StoredPlace]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        for place in self.places.values():  # indexed once, so each field's places cost O(1)
            self._by_field.setdefault(place.field_id, {})[place.id] = place

    def places_of(self, field_id: uuid.UUID) -> dict[uuid.UUID, StoredPlace]:
        return self._by_field.get(field_id, {})


# --- checking (§10.5) ---------------------------------------------------------------------------


def check(
    fieldset: FieldSet, stored: Stored, pages: Sequence[tuple[float, float]]
) -> list[FieldError]:
    """Every rule that spans items; each error names its item by path."""
    errors: list[FieldError] = []
    seen: set[uuid.UUID] = set()

    def new_id(path: str, item_id: uuid.UUID) -> None:
        if item_id in seen:
            errors.append(FieldError(path, "This id is used twice"))
        seen.add(item_id)

    labels: set[str] = set()
    for i, party in enumerate(fieldset.parties):
        new_id(f"parties[{i}].id", party.id)
        if party.label.strip().casefold() in labels:
            errors.append(FieldError(f"parties[{i}].label", "Another party has this name"))
        labels.add(party.label.strip().casefold())
    party_ids = {p.id for p in fieldset.parties}
    fields = {f.id: f for f in fieldset.fields}

    for i, item in enumerate(fieldset.fields):
        at = f"fields[{i}]"
        new_id(f"{at}.id", item.id)
        if (item.holds == "other") != (item.holds_label is not None):
            errors.append(FieldError(f"{at}.holds_label", "Name the type only for Other"))
        if (item.filled_by == "role") != (item.party_id is not None):
            errors.append(
                FieldError(f"{at}.party_id", "Name a party exactly when a party fills it")
            )
        elif item.party_id is not None and item.party_id not in party_ids:
            errors.append(FieldError(f"{at}.party_id", "No such party"))
        errors.extend(_check_dependency(at, item, fields))
        for j, place in enumerate(item.places):
            where = f"{at}.places[{j}]"
            new_id(f"{where}.id", place.id)
            before = stored.places.get(place.id)
            if before is not None and place.kind != before.kind:
                errors.append(FieldError(f"{where}.kind", "A box from the PDF keeps its kind"))
            if before is None and place.kind != "blank":
                errors.append(FieldError(f"{where}.kind", "A new box is drawn (blank)"))
            if item.holds not in MANUAL_ALLOWED[place.kind]:
                errors.append(FieldError(f"{at}.holds", f"A {place.kind} box cannot hold this"))
            errors.extend(_check_place(where, place.page, place.rect, before, pages))
    errors.extend(_check_loops(fieldset.fields))
    return errors


def _check_dependency(
    at: str, item: FieldIn, fields: Mapping[uuid.UUID, FieldIn]
) -> list[FieldError]:
    if item.depends_on is None:
        return []
    target = fields.get(item.depends_on.field_id)
    if target is None or target.id == item.id:
        return [FieldError(f"{at}.depends_on", "It depends on a field that is not here")]
    if target.holds == "checkbox":
        options = {"checked"}
    elif target.holds == "choice":
        options = {p.option_value for p in target.places if p.option_value}
    else:
        return [FieldError(f"{at}.depends_on", "Only a choice or a checkbox can be a condition")]
    if item.depends_on.option not in options:
        return [FieldError(f"{at}.depends_on", "That option is not one of the field's")]
    return []


def _check_place(
    where: str,
    page: int,
    rect: tuple[float, float, float, float],
    before: StoredPlace | None,
    pages: Sequence[tuple[float, float]],
) -> list[FieldError]:
    x0, y0, x1, y1 = rect
    if page > len(pages):
        return [FieldError(f"{where}.page", "No such page")]
    if not (x0 < x1 and y0 < y1):
        return [FieldError(f"{where}.rect", "A box needs a width and a height")]
    if before is not None and before.page == page and before.rect == rect:
        return []  # as stored: kept as the PDF or detection drew it
    width, height = pages[page - 1]
    if (
        x0 < -EDGE_TOLERANCE
        or y0 < -EDGE_TOLERANCE
        or x1 > width + EDGE_TOLERANCE
        or y1 > height + EDGE_TOLERANCE
    ):
        return [FieldError(f"{where}.rect", "The box must stay on its page")]
    if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
        return [FieldError(f"{where}.rect", f"A box is at least {MIN_SIDE:g} points on each side")]
    return []


def _check_loops(fields: Sequence[FieldIn]) -> list[FieldError]:
    """Each dependency chain walked once: O(F)."""
    depends = {f.id: f.depends_on.field_id for f in fields if f.depends_on is not None}
    index = {f.id: i for i, f in enumerate(fields)}
    state: dict[uuid.UUID, int] = {}  # 1 on the current path, 2 done
    errors: list[FieldError] = []
    for start in depends:
        path: list[uuid.UUID] = []
        node: uuid.UUID | None = start
        while node is not None and node not in state:
            state[node] = 1
            path.append(node)
            node = depends.get(node)
        if node is not None and state[node] == 1:
            errors.append(FieldError(f"fields[{index[node]}].depends_on", "These conditions loop"))
        for visited in path:
            state[visited] = 2
    return errors


# --- settling: shared values and keys (§11) -----------------------------------------------------


@dataclass
class Settled:
    """The set as it is written: shared values merged, a slug per party and a key per field."""

    parties: list[tuple[PartyIn, str]]  # with its slug, in signing order
    fields: list[tuple[FieldIn, str]]  # with its key, in the editor's order
    merged: list[dict[str, Any]] = field(default_factory=list)  # for the audit entry


def settle(fieldset: FieldSet) -> Settled:
    """One value per party for a shared value (signature, initials, signing date, name): a second
    field of the same party and value becomes more places of the first. Then slugs follow the
    parties' names and keys follow the fields' parties and labels (frozen at approval)."""
    first: dict[tuple[uuid.UUID, str], FieldIn] = {}
    kept: list[FieldIn] = []
    merged: list[dict[str, Any]] = []
    for item in fieldset.fields:
        share = (item.party_id, item.holds) if item.party_id and item.holds in SHARED else None
        owner = first.get(share) if share else None
        if owner is not None and len(owner.places) + len(item.places) <= MAX_PLACES:
            owner.places.extend(item.places)
            merged.append({"into": str(owner.id), "field": str(item.id), "label": item.label})
            continue
        if share:
            first.setdefault(share, item)
        kept.append(item)

    taken: set[str] = set()
    parties = [(p, unique(slug(p.label) or "party", taken)) for p in fieldset.parties]
    slug_of = {p.id: s for p, s in parties}
    keys: set[str] = set()
    fields: list[tuple[FieldIn, str]] = []
    for item in kept:
        role = slug_of.get(item.party_id) if item.party_id else None
        owner_name = role or "agreement"
        if role and item.holds in PARTY_VALUES:
            base = f"{role}.{item.holds}"
        else:
            base = f"{owner_name}.{name_words(item.holds_label or item.label, role)}"
        fields.append((item, unique(base, keys)))
    return Settled(parties=parties, fields=fields, merged=merged)


def rekey(
    settled: Settled, stored: Stored, new_id: Callable[[], uuid.UUID] = uuid.uuid4
) -> tuple[Settled, Stored, dict[uuid.UUID, uuid.UUID]]:
    """The same set under fresh ids, for a version made by editing (§1.2): ids are unique across
    versions, and the source keeps its own. Every reference (a field's party and condition, a
    place's field) moves with its id, and the stored set is re-keyed alike, so writing it keeps
    each place's PDF field name and each unchanged field's flag. Returns the ids too (old to new),
    for what else refers to the source's parties (the metrics' baseline). O(R + F + P)."""
    ids: dict[uuid.UUID, uuid.UUID] = {}

    def to(old: uuid.UUID) -> uuid.UUID:
        if old not in ids:
            ids[old] = new_id()
        return ids[old]

    parties = [(p.model_copy(update={"id": to(p.id)}), s) for p, s in settled.parties]
    fields = [
        (
            item.model_copy(
                update={
                    "id": to(item.id),
                    "party_id": to(item.party_id) if item.party_id else None,
                    "depends_on": item.depends_on.model_copy(
                        update={"field_id": to(item.depends_on.field_id)}
                    )
                    if item.depends_on
                    else None,
                    "places": [p.model_copy(update={"id": to(p.id)}) for p in item.places],
                }
            ),
            key,
        )
        for item, key in settled.fields
    ]
    moved = Stored(
        parties={to(i): replace(p, id=to(i)) for i, p in stored.parties.items()},
        fields={
            to(i): replace(
                f,
                id=to(i),
                party_id=to(f.party_id) if f.party_id else None,
                depends_on=(to(f.depends_on[0]), f.depends_on[1]) if f.depends_on else None,
            )
            for i, f in stored.fields.items()
        },
        places={
            to(i): replace(p, id=to(i), field_id=to(p.field_id)) for i, p in stored.places.items()
        },
    )
    return Settled(parties=parties, fields=fields, merged=settled.merged), moved, ids


def is_sensitive(item: FieldIn) -> bool:
    """Private by its type (review.values), or by its own toggle for an Other type."""
    return item.holds in SENSITIVE or (item.holds == "other" and item.sensitive)


# --- the record of changes (§1.4) ---------------------------------------------------------------

_FIELD_ATTRS = ("label", "holds", "holds_label", "filled_by", "party_id", "required", "depends_on")


def _field_attrs(item: FieldIn | StoredField) -> dict[str, Any]:
    if isinstance(item, FieldIn):
        depends = (
            (str(item.depends_on.field_id), item.depends_on.option) if item.depends_on else None
        )
    else:
        depends = (str(item.depends_on[0]), item.depends_on[1]) if item.depends_on else None
    values = {name: getattr(item, name) for name in _FIELD_ATTRS if name != "depends_on"}
    values["party_id"] = str(values["party_id"]) if values["party_id"] else None
    values["depends_on"] = list(depends) if depends else None
    return values


def unchanged(item: FieldIn, before: StoredField | None, stored: Stored) -> bool:
    """The field is as stored (its attributes and its places): a flag on it stays (§2.2)."""
    if before is None or _field_attrs(item) != _field_attrs(before):
        return False
    places = stored.places_of(item.id)
    return {p.id for p in item.places} == set(places) and all(
        places[p.id].page == p.page and places[p.id].rect == p.rect for p in item.places
    )


def changes(stored: Stored, settled: Settled) -> dict[str, Any]:
    """What a Save changed, by id: counts, and the changes themselves (at most CHANGES_KEPT)."""
    listed: list[dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "changed": 0}

    def note(what: str, change: str, item_id: uuid.UUID, label: str, **extra: Any) -> None:
        counts[change] += 1
        if len(listed) < CHANGES_KEPT:
            listed.append(
                {"what": what, "change": change, "id": str(item_id), "label": label, **extra}
            )

    new_parties = {p.id: (p, i) for i, (p, _) in enumerate(settled.parties, start=1)}
    for party_id, (party, position) in new_parties.items():
        before = stored.parties.get(party_id)
        now = {
            "label": party.label,
            "kind": party.kind,
            "kind_label": party.kind_label,
            "position": position,
        }
        if before is None:
            note("party", "added", party_id, party.label)
            continue
        was = {
            "label": before.label,
            "kind": before.kind,
            "kind_label": before.kind_label,
            "position": before.position,
        }
        diff = {k: [was[k], now[k]] for k in now if was[k] != now[k]}
        if diff:
            note("party", "changed", party_id, party.label, attributes=diff)
    for party_id, before in stored.parties.items():
        if party_id not in new_parties:
            note("party", "removed", party_id, before.label)

    new_fields = {item.id: item for item, _ in settled.fields}
    for field_id, item in new_fields.items():
        stored_field = stored.fields.get(field_id)
        if stored_field is None:
            note("field", "added", field_id, item.label, places=len(item.places))
            continue
        now_attrs, was_attrs = _field_attrs(item), _field_attrs(stored_field)
        field_diff: dict[str, Any] = {
            k: [was_attrs[k], now_attrs[k]] for k in now_attrs if was_attrs[k] != now_attrs[k]
        }
        old_places = stored.places_of(field_id)
        new_places = {p.id: p for p in item.places}
        added = len(new_places.keys() - old_places.keys())
        removed = len(old_places.keys() - new_places.keys())
        moved = sum(
            1
            for pid in new_places.keys() & old_places.keys()
            if (new_places[pid].page, new_places[pid].rect)
            != (old_places[pid].page, old_places[pid].rect)
        )
        if added or removed or moved:
            field_diff["places"] = {"added": added, "removed": removed, "moved": moved}
        if field_diff:
            note("field", "changed", field_id, item.label, attributes=field_diff)
    for field_id, gone in stored.fields.items():
        if field_id not in new_fields:
            note("field", "removed", field_id, gone.label)

    return {
        **counts,
        "merged": settled.merged,
        "changes": listed,
        "more": max(0, sum(counts.values()) - len(listed)),
    }
