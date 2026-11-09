"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { Notice, SearchField, SmallText } from "@/shared/ui";

import { HOLDS, toneOf, whoFills, type PartyRef, type VersionFields } from "./fields";
import type { Selection } from "./FieldBoxes";
import styles from "./fields.module.css";
import type { Draft, DraftField } from "./review/editor";
import { FieldForm } from "./review/FieldForm";
import { PartyList } from "./review/PartyList";
import { ThingsToCheck } from "./review/ThingsToCheck";
import { PlaceStepper } from "./review/PlaceStepper";
import type { PanelEditing } from "./review/useReview";

const STEPS = ["Read the document", "Finding who fills each field", "Checking"] as const;
const STEP_OF_STAGE: Record<string, number> = { read: 0, ai: 1, derive: 2, store: 2, done: 3 };

export type Filter = { kind: "all" } | { kind: "party"; id: string } | { kind: "sender" };
type Row = { id: string; field: DraftField; depth: number };

/**
 * Scrolls a list just enough to show one of its rows, leaving the page where it is: smoothly,
 * unless the person asked for less motion.
 */
function showWithin(list: HTMLElement, row: Element) {
  const outer = list.getBoundingClientRect();
  const inner = row.getBoundingClientRect();
  const by = inner.top < outer.top ? inner.top - outer.top : inner.bottom > outer.bottom ? inner.bottom - outer.bottom : 0;
  if (by === 0) return;
  const top = list.scrollTop + by;
  const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  if (typeof list.scrollTo === "function") list.scrollTo({ top, behavior: still ? "auto" : "smooth" });
  else list.scrollTop = top;
}

function placesFound(view: VersionFields): string {
  const places = view.pending.reduce((sum, found) => sum + found.placements.length, 0);
  if (view.fields_from === "none") return "Nothing to fill found";
  const counted = `${places} ${places === 1 ? "place" : "places"} to fill`;
  return view.fields_from === "blanks" ? `No form fields; ${counted}` : counted;
}

/** "Only when … is chosen": a field's condition, in the option's own words. */
export function condition(field: DraftField, byId: ReadonlyMap<string, DraftField>): string | null {
  if (!field.depends_on) return null;
  const parent = byId.get(field.depends_on.field_id);
  if (!parent) return null;
  if (field.depends_on.option === "checked") return `Only when “${parent.label}” is ticked`;
  const place = parent.places.find((p) => p.option_value === field.depends_on?.option);
  return `Only when “${place?.option_text ?? field.depends_on.option}” is chosen`;
}

/**
 * Every field of a version, linked with the PDF (Phase 5 LLD §6.2-6.4, Phase 6 §7): pick one here
 * and the viewer brings it into view; pick a box there and it is chosen here. Fields that need a
 * look come first; choices list their options with the fields that only apply under each. While
 * the AI works, the places already found are listed and drawn. When editing, the parties can be
 * changed and a chosen field's form takes the overview's place until "Done".
 */
export function FieldsPanel({
  view,
  draft,
  selected,
  onSelect,
  onClear,
  filter,
  onFilter,
  editing,
}: {
  view: VersionFields;
  draft: Draft;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
  onClear: () => void;
  filter: Filter;
  onFilter: (filter: Filter) => void;
  editing: PanelEditing | null;
}) {
  const [search, setSearch] = useState("");
  const parties: PartyRef[] = draft.parties;
  const byId = useMemo(() => new Map(draft.fields.map((field) => [field.id, field])), [draft.fields]);
  // A field chosen on the PDF (or with the keys) is brought into view in the list too.
  const listRef = useRef<HTMLUListElement>(null);
  const rowId = selected ? (selected.kind === "field" ? `field-${selected.id}` : `pending-${selected.id}`) : null;
  useEffect(() => {
    const list = listRef.current;
    const row = rowId ? [...(list?.children ?? [])].find((child) => child.id === rowId) : undefined;
    if (list && row) showWithin(list, row);
  }, [rowId]);

  const rows = useMemo<Row[]>(() => {
    const query = search.trim().toLowerCase();
    const shown = (field: DraftField) =>
      (filter.kind === "all" ||
        (filter.kind === "sender" && field.filled_by === "sender") ||
        (filter.kind === "party" && field.filled_by === "role" && field.party_id === filter.id)) &&
      (!query || field.label.toLowerCase().includes(query));
    const ordered = [...draft.fields].sort((a, b) => Number(Boolean(b.needs_review)) - Number(Boolean(a.needs_review)));
    if (query || filter.kind !== "all") {
      return ordered.filter(shown).map((field) => ({ id: field.id, field, depth: 0 }));
    }
    // A tree: a field that applies under an option sits under its choice.
    const children = new Map<string, DraftField[]>();
    for (const field of ordered) {
      if (field.depends_on && byId.has(field.depends_on.field_id)) {
        children.set(field.depends_on.field_id, [...(children.get(field.depends_on.field_id) ?? []), field]);
      }
    }
    const out: Row[] = [];
    const seen = new Set<string>();
    const visit = (field: DraftField, depth: number) => {
      if (seen.has(field.id)) return; // an unsaved loop is refused at Save; never drawn forever
      seen.add(field.id);
      out.push({ id: field.id, field, depth });
      for (const child of children.get(field.id) ?? []) visit(child, depth + 1);
    };
    for (const field of ordered) if (!field.depends_on || !byId.has(field.depends_on.field_id)) visit(field, 0);
    for (const field of ordered) visit(field, 0);
    return out;
  }, [draft.fields, byId, filter, search]);

  if (view.status === "detecting") {
    const step = STEP_OF_STAGE[view.stage ?? "read"] ?? 0;
    return (
      <div className={styles.panel}>
        <ol className={styles.steps} aria-label="Finding fields">
          {STEPS.map((label, index) => (
            <li key={label} className={index < step ? styles.done : index === step ? styles.running : styles.next}>
              <span aria-hidden="true">{index < step ? "✓" : index === step ? "●" : "○"}</span>
              <span>{index === 0 && step > 0 ? `${label}: ${placesFound(view)}` : label}</span>
            </li>
          ))}
        </ol>
        {view.pending.length > 0 ? (
          <ul ref={listRef} className={styles.list} aria-label="Places found">
            {view.pending.map((found) => (
              <li key={found.id} id={`pending-${found.id}`}>
                <button
                  type="button"
                  className={`${styles.item}${selected?.kind === "pending" && selected.id === found.id ? ` ${styles.selected}` : ""}`}
                  onClick={() => onSelect({ kind: "pending", id: found.id, place: 0 })}
                >
                  <span className={styles.label}>{found.label ?? "A place to fill"}</span>
                  <span className={styles.meta}>Finding who fills this…</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    );
  }

  const chosen = selected?.kind === "field" ? byId.get(selected.id) : undefined;
  if (editing && chosen && selected?.kind === "field") {
    return (
      <FieldForm
        key={chosen.id}
        field={chosen}
        draft={draft}
        place={selected.place}
        editing={editing}
        onPlace={(place) => onSelect({ kind: "field", id: chosen.id, place })}
        onSelect={onSelect}
        onDone={onClear}
      />
    );
  }

  const sender = draft.fields.filter((field) => field.filled_by === "sender").length;
  const move = (event: KeyboardEvent<HTMLUListElement>) => {
    const index = rows.findIndex((row) => row.id === chosen?.id);
    const next =
      event.key === "ArrowDown" ? Math.min(index + 1, rows.length - 1) : event.key === "ArrowUp" ? Math.max(index - 1, 0) : null;
    if (event.key === "Enter" && chosen) {
      event.preventDefault();
      onSelect({ kind: "field", id: chosen.id, place: 0 });
    } else if (next !== null && rows[next]) {
      event.preventDefault();
      onSelect({ kind: "field", id: rows[next].id, place: 0 });
    }
  };
  const inReview = view.status === "ready";

  return (
    <div className={styles.panel}>
      {draft.fields.length > 0 ? (
        <p className={styles.headline}>
          {`${draft.fields.length} ${draft.fields.length === 1 ? "field" : "fields"} for ${parties.length} ${parties.length === 1 ? "party" : "parties"}`}
        </p>
      ) : null}
      {view.flags.no_fields && draft.fields.length === 0 ? (
        <Notice>
          {editing?.canDraw
            ? "We couldn't find places to fill or sign. Add them with Add field above the document."
            : "We couldn't find places to fill or sign."}
        </Notice>
      ) : null}
      {view.found_again_failed ? (
        <Notice tone="warning">{`${view.found_again_failed}. These are the fields found before.`}</Notice>
      ) : null}
      {inReview ? (
        <ThingsToCheck
          warnings={view.warnings}
          stale={(editing?.review.changes ?? 0) > 0}
          onShow={(fieldId) => onSelect({ kind: "field", id: fieldId, place: 0 })}
        />
      ) : null}
      {editing && !editing.canDraw ? (
        <SmallText>Adding and moving boxes on the document needs a larger screen. Everything else works here.</SmallText>
      ) : null}
      <PartyList
        parties={draft.parties}
        fields={draft.fields}
        sender={sender}
        edit={editing ? editing.review.edit : null}
      />
      {draft.fields.length > 0 ? (
        <>
          <div className={styles.filters} role="group" aria-label="Show fields of">
            <FilterChip active={filter.kind === "all"} onClick={() => onFilter({ kind: "all" })}>
              All
            </FilterChip>
            {parties.map((party) => (
              <FilterChip
                key={party.id}
                active={filter.kind === "party" && filter.id === party.id}
                onClick={() => onFilter({ kind: "party", id: party.id })}
              >
                {party.label}
              </FilterChip>
            ))}
            {sender > 0 ? (
              <FilterChip active={filter.kind === "sender"} onClick={() => onFilter({ kind: "sender" })}>
                Before sending
              </FilterChip>
            ) : null}
          </div>
          <SearchField label="Find a field" value={search} onChange={(event) => setSearch(event.target.value)} />
          <ul
            ref={listRef}
            className={styles.list}
            role="listbox"
            aria-label="Fields"
            tabIndex={0}
            aria-activedescendant={chosen ? `field-${chosen.id}` : undefined}
            onKeyDown={move}
          >
            {rows.map((row) => (
              <li
                key={row.id}
                id={`field-${row.id}`}
                role="option"
                aria-selected={chosen?.id === row.id}
                className={`${styles.item}${chosen?.id === row.id ? ` ${styles.selected}` : ""}`}
                style={{ paddingLeft: 12 + row.depth * 16 }}
                onClick={() => onSelect({ kind: "field", id: row.id, place: 0 })}
              >
                <span className={`${styles.dot} ${styles[toneOf(row.field, parties)]}`} aria-hidden="true" />
                <span className={styles.label}>{row.field.label}</span>
                <span className={styles.meta}>
                  {[
                    whoFills(row.field, parties),
                    row.field.holds === "other" ? row.field.holds_label || HOLDS.other : HOLDS[row.field.holds],
                    row.field.required ? "Required" : "Optional",
                    row.field.places.length > 1 ? `${row.field.places.length} places` : null,
                    row.field.needs_review ? "Needs a look" : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </li>
            ))}
          </ul>
          {rows.length === 0 ? <SmallText>No field matches.</SmallText> : null}
          {chosen && selected?.kind === "field" ? (
            <FieldDetails
              field={chosen}
              parties={parties}
              byId={byId}
              place={selected.place}
              onPlace={(place) => onSelect({ kind: "field", id: chosen.id, place })}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button type="button" aria-pressed={active} className={`${styles.chip}${active ? ` ${styles.chipOn}` : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

function FieldDetails({
  field,
  parties,
  byId,
  place,
  onPlace,
}: {
  field: DraftField;
  parties: readonly PartyRef[];
  byId: ReadonlyMap<string, DraftField>;
  place: number;
  onPlace: (place: number) => void;
}) {
  const places = field.places.length;
  const options = field.holds === "choice" ? field.places : [];
  const when = condition(field, byId);
  // The list's row already names the field and who fills it: this says only what the row can't.
  if (!when && !field.sensitive && !field.needs_review && options.length === 0 && places <= 1) return null;
  return (
    <section className={styles.details} aria-label={`More about ${field.label}`} aria-live="polite">
      {when ? <SmallText>{when}</SmallText> : null}
      {field.sensitive ? <SmallText>{`Private to ${whoFills(field, parties)}: shown to nobody else`}</SmallText> : null}
      {field.needs_review ? <Notice tone="warning">{`Needs a look: ${field.needs_review}.`}</Notice> : null}
      {options.length > 0 ? (
        <ul className={styles.options} aria-label="Options">
          {options.map((option) => {
            const inside = [...byId.values()].filter(
              (other) => other.depends_on?.field_id === field.id && other.depends_on.option === option.option_value,
            );
            return (
              <li key={option.id}>
                <span aria-hidden="true">( ) </span>
                {option.option_text ?? option.option_value}
                {inside.length > 0 ? <span className={styles.meta}>{` → also asks ${inside.map((f) => f.label).join(", ")}`}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {places > 1 ? <PlaceStepper place={place} places={places} onPlace={onPlace} /> : null}
    </section>
  );
}
