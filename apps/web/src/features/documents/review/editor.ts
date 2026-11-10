/**
 * The review editor's state as pure functions (Phase 6 LLD §3-§5, §12): a draft of a version's
 * parties, fields and places by id, every edit a function from one draft to the next, and an undo
 * history over them. Nothing here talks to the API or the DOM: the page turns a fields view into
 * a draft, edits it, and turns it back into the save body. Ids of new items are made here (UUIDs),
 * so a retried save, undo and the audit entry refer to the same items (§6.3).
 */
import type { components } from "@signora/contracts";

import type { VersionFields } from "../fields";

export type FieldSet = components["schemas"]["FieldSet"];
export type Holds = components["schemas"]["FieldIn"]["holds"];
export type PlaceKind = components["schemas"]["PlaceIn"]["kind"];
export type PartyKind = components["schemas"]["PartyIn"]["kind"];
export type FilledBy = components["schemas"]["FieldIn"]["filled_by"];
export type Rect = [number, number, number, number];
export type PageSize = { width: number; height: number };

export type DraftParty = { id: string; label: string; kind: PartyKind; kind_label: string | null };

export type DraftPlace = {
  id: string;
  page: number;
  rect: Rect;
  kind: PlaceKind; // a PDF box keeps its kind; a drawn one is "blank"
  option_value: string | null;
  option_text: string | null;
};

export type DraftField = {
  id: string;
  key: string | null; // the server's, once saved (shown, never edited)
  label: string;
  holds: Holds;
  holds_label: string | null;
  format: string | null; // how a date or a part of one is written; null: the type's default
  filled_by: FilledBy;
  party_id: string | null;
  required: boolean;
  sensitive: boolean;
  depends_on: { field_id: string; option: string } | null;
  needs_review: string | null; // a flag detection left; editing the field clears it (§2.2)
  places: DraftPlace[];
};

export type Draft = { parties: DraftParty[]; fields: DraftField[] };

export const MIN_SIDE = 8; // PDF points: the smallest box (the server's limit too)
export const MAX_PARTIES = 20;
const EDGE = 0; // boxes stay on their page

/** Private by type; an Other type has its own toggle (the server's rule, review.values). */
export const PRIVATE: ReadonlySet<Holds> = new Set<Holds>(["tax_id", "bank_account", "date_of_birth"]);
/** A choice or a checkbox can be a condition (§4). */
export const CONDITIONS: ReadonlySet<Holds> = new Set<Holds>(["choice", "checkbox"]);

/** A new box's size when clicked rather than drawn (§5), in PDF points. */
export function defaultSize(holds: Holds): [number, number] {
  switch (holds) {
    case "signature":
      return [180, 36];
    case "initials":
      return [60, 30];
    case "date_signed":
    case "date":
      return [100, 20];
    case "day":
    case "year":
      return [36, 20];
    case "month":
      return [80, 20];
    case "checkbox":
    case "choice":
      return [12, 12];
    default:
      return [160, 20];
  }
}

export const newId = (): string => crypto.randomUUID();

// --- from the API and back --------------------------------------------------------------------

/** The fields view as a draft: parties in signing order, conditions by field id. */
export function fromView(view: VersionFields): Draft {
  const idOfKey = new Map(view.fields.map((field) => [field.key, field.id]));
  return {
    parties: [...view.roles]
      .sort((a, b) => a.position - b.position)
      .map((role) => ({ id: role.id, label: role.label, kind: role.kind, kind_label: role.kind_label })),
    fields: view.fields.map((field) => ({
      id: field.id,
      key: field.key,
      label: field.label,
      holds: field.holds,
      holds_label: field.holds_label,
      format: field.format,
      filled_by: field.filled_by,
      party_id: field.party_id,
      required: field.required,
      sensitive: field.sensitive,
      depends_on:
        field.depends_on && idOfKey.has(field.depends_on.key)
          ? { field_id: idOfKey.get(field.depends_on.key) ?? "", option: field.depends_on.option }
          : null,
      needs_review: field.needs_review,
      places: field.placements.map((place) => ({
        id: place.id ?? newId(),
        page: place.page,
        rect: [place.rect[0] ?? 0, place.rect[1] ?? 0, place.rect[2] ?? 0, place.rect[3] ?? 0],
        kind: place.kind as PlaceKind,
        option_value: place.option_value,
        option_text: place.option_text,
      })),
    })),
  };
}

/** The save body: the whole set as the editor holds it, with the revision it started from. */
export function toFieldSet(draft: Draft, revision: number): FieldSet {
  return {
    revision,
    parties: draft.parties.map((party) => ({
      id: party.id,
      label: party.label.trim(),
      kind: party.kind,
      kind_label: party.kind_label === null ? null : party.kind_label.trim(), // "" is refused, and named
    })),
    fields: draft.fields.map((field) => ({
      id: field.id,
      label: field.label.trim(),
      holds: field.holds,
      holds_label: field.holds === "other" ? field.holds_label?.trim() ?? "" : null,
      format: field.format,
      filled_by: field.filled_by,
      party_id: field.filled_by === "role" ? field.party_id : null,
      required: field.required,
      sensitive: field.holds === "other" ? field.sensitive : PRIVATE.has(field.holds),
      depends_on: field.depends_on,
      places: field.places.map((place) => ({
        id: place.id,
        page: place.page,
        rect: place.rect,
        kind: place.kind,
        option_value: place.option_value,
        option_text: place.option_text,
      })),
    })),
  };
}

// --- geometry ---------------------------------------------------------------------------------

/** A box kept on its page and at least MIN_SIDE on each side; its size kept when it is moved. */
export function clampRect(rect: Rect, page: PageSize, keepSize = true): Rect {
  let [x0, y0, x1, y1] = rect;
  if (x1 < x0) [x0, x1] = [x1, x0];
  if (y1 < y0) [y0, y1] = [y1, y0];
  const width = Math.min(Math.max(x1 - x0, MIN_SIDE), page.width);
  const height = Math.min(Math.max(y1 - y0, MIN_SIDE), page.height);
  if (keepSize) {
    x0 = Math.min(Math.max(x0, EDGE), page.width - width);
    y0 = Math.min(Math.max(y0, EDGE), page.height - height);
    return [round(x0), round(y0), round(x0 + width), round(y0 + height)];
  }
  x0 = Math.max(x0, EDGE);
  y0 = Math.max(y0, EDGE);
  x1 = Math.min(Math.max(x1, x0 + MIN_SIDE), page.width);
  y1 = Math.min(Math.max(y1, y0 + MIN_SIDE), page.height);
  return [round(Math.min(x0, x1 - MIN_SIDE)), round(Math.min(y0, y1 - MIN_SIDE)), round(x1), round(y1)];
}

const round = (value: number) => Math.round(value * 100) / 100;

/** A box of the default size for its type, centred where the person clicked, on its page. */
export function boxAt(holds: Holds, x: number, y: number, page: PageSize): Rect {
  const [width, height] = defaultSize(holds);
  return clampRect([x - width / 2, y - height / 2, x + width / 2, y + height / 2], page);
}

// --- fields -----------------------------------------------------------------------------------

type FieldPatch = Partial<Omit<DraftField, "id" | "key" | "places" | "needs_review">>;

function mapField(draft: Draft, id: string, change: (field: DraftField) => DraftField): Draft {
  return { ...draft, fields: draft.fields.map((field) => (field.id === id ? change(field) : field)) };
}

/** Conditions on a field that can no longer be one (deleted, or no longer a choice or checkbox). */
function dropConditionsOn(fields: DraftField[], gone: ReadonlySet<string>): DraftField[] {
  return fields.map((field) =>
    field.depends_on && gone.has(field.depends_on.field_id) ? { ...field, depends_on: null } : field,
  );
}

/** Change a field's attributes. Editing a field clears its "needs a look" flag (§2.2). */
export function updateField(draft: Draft, id: string, patch: FieldPatch): Draft {
  let next = mapField(draft, id, (field) => {
    const changed: DraftField = { ...field, ...patch, needs_review: null };
    if (changed.holds !== "other") changed.holds_label = null;
    else if (changed.holds_label === null) changed.holds_label = "";
    if (changed.holds !== field.holds) changed.format = null; // another type: its default
    if (changed.filled_by !== "role") changed.party_id = null;
    if (changed.holds !== "other") changed.sensitive = PRIVATE.has(changed.holds);
    return changed;
  });
  const field = next.fields.find((candidate) => candidate.id === id);
  if (field && !CONDITIONS.has(field.holds)) next = { ...next, fields: dropConditionsOn(next.fields, new Set([id])) };
  return next;
}

/** A new field with one place (§5): drawn, filled by the chosen party, else not asked. */
export function newField(holds: Holds, label: string, partyId: string | null, place: Omit<DraftPlace, "id" | "kind">): DraftField {
  return {
    id: newId(),
    key: null,
    label,
    holds,
    holds_label: holds === "other" ? "" : null,
    format: null,
    filled_by: partyId ? "role" : "none",
    party_id: partyId,
    required: true,
    sensitive: PRIVATE.has(holds),
    depends_on: null,
    needs_review: null,
    places: [{ id: newId(), kind: "blank", ...place }],
  };
}

export function addField(draft: Draft, field: DraftField): Draft {
  return { ...draft, fields: [...draft.fields, field] };
}

export function deleteField(draft: Draft, id: string): Draft {
  return { ...draft, fields: dropConditionsOn(draft.fields.filter((field) => field.id !== id), new Set([id])) };
}

// --- places -----------------------------------------------------------------------------------

export function findPlace(draft: Draft, placeId: string): { field: DraftField; place: DraftPlace; index: number } | null {
  for (const field of draft.fields) {
    const index = field.places.findIndex((place) => place.id === placeId);
    const place = field.places[index];
    if (place) return { field, place, index };
  }
  return null;
}

function mapPlace(draft: Draft, placeId: string, change: (place: DraftPlace) => DraftPlace): Draft {
  return {
    ...draft,
    fields: draft.fields.map((field) =>
      field.places.some((place) => place.id === placeId)
        ? { ...field, needs_review: null, places: field.places.map((place) => (place.id === placeId ? change(place) : place)) }
        : field,
    ),
  };
}

/**
 * Move or resize a place, kept on its page and at least MIN_SIDE (§5). A place already there (at
 * its page's edge, at the smallest size) is left as it is: no edit, nothing to undo or save.
 */
export function setRect(draft: Draft, placeId: string, rect: Rect, pages: readonly PageSize[], keepSize = true): Draft {
  const found = findPlace(draft, placeId);
  const page = found && pages[found.place.page - 1];
  if (!found || !page) return draft;
  const next = clampRect(rect, page, keepSize);
  if (next.every((value, index) => value === found.place.rect[index])) return draft;
  return mapPlace(draft, placeId, (place) => ({ ...place, rect: next }));
}

/** Nudge a place by whole points (arrow keys: 1, with Shift 10). */
export function nudge(draft: Draft, placeId: string, dx: number, dy: number, pages: readonly PageSize[]): Draft {
  const found = findPlace(draft, placeId);
  if (!found) return draft;
  const [x0, y0, x1, y1] = found.place.rect;
  return setRect(draft, placeId, [x0 + dx, y0 + dy, x1 + dx, y1 + dy], pages);
}

/**
 * A place made larger or smaller by ``factor`` around its centre (the field form's − and +): at
 * least MIN_SIDE on each side, kept on its page.
 */
export function resize(draft: Draft, placeId: string, factor: number, pages: readonly PageSize[]): Draft {
  const found = findPlace(draft, placeId);
  if (!found) return draft;
  const [x0, y0, x1, y1] = found.place.rect;
  const width = Math.max((x1 - x0) * factor, MIN_SIDE);
  const height = Math.max((y1 - y0) * factor, MIN_SIDE);
  const [cx, cy] = [(x0 + x1) / 2, (y0 + y1) / 2];
  return setRect(draft, placeId, [cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2], pages, false);
}

/** An option's words (a choice's place): what the signer reads; its value, what a condition names, stays. */
export function setOptionText(draft: Draft, placeId: string, text: string): Draft {
  return mapPlace(draft, placeId, (place) => ({ ...place, option_text: text }));
}

/** The next option's name for a new place of a choice: the first "Option n" no place of it has. */
export function nextOptionName(field: DraftField): string {
  const taken = new Set(field.places.map((place) => place.option_value));
  let n = field.places.length + 1;
  while (taken.has(`Option ${n}`)) n += 1;
  return `Option ${n}`;
}

export function addPlace(draft: Draft, fieldId: string, place: Omit<DraftPlace, "id" | "kind">): Draft {
  return mapField(draft, fieldId, (field) => ({
    ...field,
    needs_review: null,
    places: [...field.places, { id: newId(), kind: "blank", ...place }],
  }));
}

/** Remove a place; a field's last place takes the field with it (the page asks first, §5). */
export function deletePlace(draft: Draft, placeId: string): Draft {
  const found = findPlace(draft, placeId);
  if (!found) return draft;
  if (found.field.places.length === 1) return deleteField(draft, found.field.id);
  return mapField(draft, found.field.id, (field) => ({
    ...field,
    needs_review: null,
    places: field.places.filter((place) => place.id !== placeId),
  }));
}

/** "Make separate field": a place becomes a field of its own with the same attributes (§5). */
export function splitPlace(draft: Draft, placeId: string): { draft: Draft; fieldId: string | null } {
  const found = findPlace(draft, placeId);
  if (!found || found.field.places.length < 2) return { draft, fieldId: null };
  const separate: DraftField = {
    ...found.field,
    id: newId(),
    key: null,
    label: `${found.field.label} (${found.index + 1})`,
    needs_review: null,
    places: [found.place],
  };
  const without = mapField(draft, found.field.id, (field) => ({
    ...field,
    places: field.places.filter((place) => place.id !== placeId),
  }));
  return { draft: addField(without, separate), fieldId: separate.id };
}

/** "On every page": the place copied to the same spot on each page that has none of the field's. */
export function onEveryPage(draft: Draft, placeId: string, pages: readonly PageSize[]): Draft {
  const found = findPlace(draft, placeId);
  if (!found) return draft;
  const taken = new Set(found.field.places.map((place) => place.page));
  const copies: DraftPlace[] = [];
  pages.forEach((page, index) => {
    if (taken.has(index + 1)) return;
    copies.push({ ...found.place, id: newId(), kind: "blank", page: index + 1, rect: clampRect(found.place.rect, page) });
  });
  return mapField(draft, found.field.id, (field) => ({ ...field, needs_review: null, places: [...field.places, ...copies] }));
}

// --- parties (§3) -----------------------------------------------------------------------------

/** Signers sign first, then countersigners: a new party joins the end of its group. */
function ordered(parties: DraftParty[]): DraftParty[] {
  return [...parties.filter((p) => p.kind === "signer"), ...parties.filter((p) => p.kind === "countersigner")];
}

export function addParty(draft: Draft, party: Omit<DraftParty, "id">): { draft: Draft; partyId: string } {
  const id = newId();
  return { draft: { ...draft, parties: ordered([...draft.parties, { ...party, id }]) }, partyId: id };
}

export function updateParty(draft: Draft, id: string, patch: Partial<Omit<DraftParty, "id">>): Draft {
  return { ...draft, parties: ordered(draft.parties.map((party) => (party.id === id ? { ...party, ...patch } : party))) };
}

/** Up or down within its group (signers among signers, countersigners among countersigners). */
export function moveParty(draft: Draft, id: string, by: -1 | 1): Draft {
  const index = draft.parties.findIndex((party) => party.id === id);
  const party = draft.parties[index];
  const other = draft.parties[index + by];
  if (!party || !other || other.kind !== party.kind) return draft;
  const parties = [...draft.parties];
  parties[index] = other;
  parties[index + by] = party;
  return { ...draft, parties };
}

export type PartyFate = { kind: "move"; to: string } | { kind: "none" } | { kind: "delete" };

/** Remove a party; its fields move to another party, become "Not asked", or go (§3). Two parties
 * the AI split are merged by moving one into the other; shared values merge when saved. */
export function removeParty(draft: Draft, id: string, fate: PartyFate): Draft {
  const parties = draft.parties.filter((party) => party.id !== id);
  const theirs = new Set(draft.fields.filter((field) => field.party_id === id).map((field) => field.id));
  if (fate.kind === "delete") {
    return { parties, fields: dropConditionsOn(draft.fields.filter((field) => !theirs.has(field.id)), theirs) };
  }
  return {
    parties,
    fields: draft.fields.map((field) =>
      theirs.has(field.id)
        ? fate.kind === "move"
          ? { ...field, party_id: fate.to, needs_review: null }
          : { ...field, filled_by: "none" as const, party_id: null, needs_review: null }
        : field,
    ),
  };
}

// --- history ----------------------------------------------------------------------------------

/** Undo and redo over the unsaved edits (§5): Save makes them final and starts a new history. */
export type History = { past: Draft[]; present: Draft; future: Draft[]; last?: string | undefined };

const KEPT = 200;

export const begin = (draft: Draft): History => ({ past: [], present: draft, future: [] });

/** One edit. Edits with the same ``merge`` key in a row (typing a name) are one step to undo and
 * one change to save. */
export function apply(history: History, edit: (draft: Draft) => Draft, merge?: string): History {
  const next = edit(history.present);
  if (next === history.present) return history;
  if (merge !== undefined && history.last === merge && history.past.length > 0) {
    return { ...history, present: next, future: [], last: merge };
  }
  return { past: [...history.past, history.present].slice(-KEPT), present: next, future: [], last: merge };
}

export function undo(history: History): History {
  const previous = history.past.at(-1);
  if (!previous) return history;
  return { past: history.past.slice(0, -1), present: previous, future: [history.present, ...history.future] };
}

export function redo(history: History): History {
  const [next, ...rest] = history.future;
  if (!next) return history;
  return { past: [...history.past, history.present], present: next, future: rest };
}

/** An edit's undo step merges with the one before when they share this key (typing in one box). */
export type Edit = (change: (draft: Draft) => Draft, merge?: string) => void;

/** How many edits are unsaved (the save bar's count). */
export const unsaved = (history: History): number => history.past.length;
