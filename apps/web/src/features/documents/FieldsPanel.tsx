"use client";

import { useEffect, useMemo, useState } from "react";

import { ExpandableList, ExpandableRow, Notice, SearchField, Section, SmallText } from "@/shared/ui";

import { HOLDS, toneOf, whoFills, type PartyRef, type VersionFields } from "./fields";
import type { Selection } from "./FieldBoxes";
import styles from "./fields.module.css";
import { AddField, PlacingStatus } from "./review/AddField";
import type { Draft, DraftField } from "./review/editor";
import { FieldForm } from "./review/FieldForm";
import { PartyList } from "./review/PartyList";
import { PlaceStepper } from "./review/PlaceStepper";
import { ThingsToCheck } from "./review/ThingsToCheck";
import type { PanelEditing } from "./review/useReview";

const STEPS = ["Read the document", "Finding who fills each field", "Checking"] as const;
const STEP_OF_STAGE: Record<string, number> = { read: 0, ai: 1, derive: 2, store: 2, done: 3 };
const ADD_ROW = "add-field";

export type Filter = { kind: "all" } | { kind: "party"; id: string } | { kind: "sender" };
type Row = { id: string; field: DraftField; depth: number };

/** Brings a chosen field's row into view, unless the person asked for less motion (smoothly). */
function bringIntoView(row: Element) {
  const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  row.scrollIntoView?.({ block: "nearest", behavior: still ? "auto" : "smooth" });
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

const typeOf = (field: DraftField) => (field.holds === "other" ? field.holds_label || HOLDS.other : HOLDS[field.holds]);

/**
 * A version's fields beside the PDF (Phase 5 LLD §6.2-6.4, Phase 6 §7.1), in three sections:
 * Things to check (in review), Who signs, and Fields. Each field is a row that opens in place:
 * choosing it here or its box on the PDF opens it and brings the box into view; its details are
 * editable for people with edit access. "+ Add field" is the list's first row. While the AI works,
 * the places already found are listed and drawn.
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
  const [adding, setAdding] = useState(false);
  const parties: PartyRef[] = draft.parties;
  const byId = useMemo(() => new Map(draft.fields.map((field) => [field.id, field])), [draft.fields]);
  // A field chosen on the PDF (or from a warning) is brought into view in the list too.
  const rowId = selected ? (selected.kind === "field" ? `field-${selected.id}` : `pending-${selected.id}`) : null;
  useEffect(() => {
    const row = rowId ? document.getElementById(rowId) : null;
    if (row) bringIntoView(row);
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
      <Section title="Fields">
        <ol className={styles.steps} aria-label="Finding fields">
          {STEPS.map((label, index) => (
            <li key={label} className={index < step ? styles.done : index === step ? styles.running : styles.next}>
              <span aria-hidden="true">{index < step ? "✓" : index === step ? "●" : "○"}</span>
              <span>{index === 0 && step > 0 ? `${label}: ${placesFound(view)}` : label}</span>
            </li>
          ))}
        </ol>
        {view.pending.length > 0 ? (
          <ExpandableList label="Places found">
            {view.pending.map((found) => (
              <ExpandableRow
                key={found.id}
                id={`pending-${found.id}`}
                title={found.label ?? "A place to fill"}
                meta="Finding who fills this…"
                expanded={selected?.kind === "pending" && selected.id === found.id}
                regionLabel={found.label ?? "A place to fill"}
                onToggle={() => onSelect({ kind: "pending", id: found.id, place: 0 })}
              />
            ))}
          </ExpandableList>
        ) : null}
      </Section>
    );
  }

  const chosen = selected?.kind === "field" ? byId.get(selected.id) : undefined;
  const sender = draft.fields.filter((field) => field.filled_by === "sender").length;
  const inReview = view.status === "ready";
  const tool = editing?.tool ?? null;
  const filteredParty = filter.kind === "party" ? filter.id : null;

  return (
    <>
      {inReview && view.warnings.length > 0 ? (
        <Section title="Things to check">
          <ThingsToCheck
            warnings={view.warnings}
            stale={(editing?.review.changes ?? 0) > 0}
            onShow={(fieldId) => onSelect({ kind: "field", id: fieldId, place: 0 })}
            onAddSignature={
              editing
                ? (partyId) => editing.startPlacing({ kind: "field", holds: "signature", filled_by: "role", party_id: partyId })
                : null
            }
          />
        </Section>
      ) : null}
      <Section title="Who signs">
        <PartyList parties={draft.parties} fields={draft.fields} sender={sender} edit={editing ? editing.review.edit : null} />
      </Section>
      <Section title={`Fields · ${draft.fields.length}`}>
        {view.flags.no_fields && draft.fields.length === 0 ? (
          <Notice>{editing ? "We couldn't find places to fill or sign. Add them below." : "We couldn't find places to fill or sign."}</Notice>
        ) : null}
        {view.found_again_failed ? (
          <Notice tone="warning">{`${view.found_again_failed}. These are the fields found before.`}</Notice>
        ) : null}
        {editing && !editing.canDraw ? (
          <SmallText>Moving boxes on the document needs a larger screen; their numbers can be changed here.</SmallText>
        ) : null}
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
                  {party.label || "Unnamed party"}
                </FilterChip>
              ))}
              {sender > 0 ? (
                <FilterChip active={filter.kind === "sender"} onClick={() => onFilter({ kind: "sender" })}>
                  Before sending
                </FilterChip>
              ) : null}
            </div>
            <SearchField label="Find a field" value={search} onChange={(event) => setSearch(event.target.value)} />
          </>
        ) : null}
        <ExpandableList label="Fields">
          {editing ? (
            <ExpandableRow
              id={ADD_ROW}
              tone="add"
              title={tool?.kind === "field" ? "Placing a new field" : "Add field"}
              expanded={adding || tool?.kind === "field"}
              regionLabel="New field"
              onToggle={() => {
                if (tool?.kind === "field") return editing.cancelPlacing();
                setAdding(!adding);
                onClear();
              }}
            >
              {tool?.kind === "field" ? (
                <PlacingStatus tool={tool} onCancel={editing.cancelPlacing} />
              ) : (
                <AddField
                  parties={draft.parties}
                  partyId={filteredParty}
                  canDraw={editing.canDraw}
                  onPlace={(next) => {
                    setAdding(false);
                    editing.startPlacing(next);
                  }}
                />
              )}
            </ExpandableRow>
          ) : null}
          {rows.map((row) => {
            const open = chosen?.id === row.id && selected?.kind === "field";
            return (
              <ExpandableRow
                key={row.id}
                id={`field-${row.id}`}
                depth={row.depth}
                lead={<span className={`${styles.dot} ${styles[toneOf(row.field, parties)]}`} aria-hidden="true" />}
                title={row.field.label || "Unnamed field"}
                meta={[
                  whoFills(row.field, parties),
                  typeOf(row.field),
                  row.field.required ? "Required" : "Optional",
                  row.field.places.length > 1 ? `${row.field.places.length} places` : null,
                  row.field.needs_review ? "Needs a look" : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
                expanded={open}
                regionLabel={`Details of ${row.field.label || "field"}`}
                onToggle={() => (open ? onClear() : onSelect({ kind: "field", id: row.id, place: 0 }))}
              >
                {open && selected?.kind === "field" ? (
                  editing ? (
                    <FieldForm
                      field={row.field}
                      draft={draft}
                      place={selected.place}
                      editing={editing}
                      onPlace={(place) => onSelect({ kind: "field", id: row.id, place })}
                      onSelect={onSelect}
                      onDone={onClear}
                    />
                  ) : (
                    <FieldDetails
                      field={row.field}
                      parties={parties}
                      byId={byId}
                      place={selected.place}
                      onPlace={(place) => onSelect({ kind: "field", id: row.id, place })}
                    />
                  )
                ) : null}
              </ExpandableRow>
            );
          })}
        </ExpandableList>
        {draft.fields.length > 0 && rows.length === 0 ? <SmallText>No field matches.</SmallText> : null}
      </Section>
    </>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button type="button" aria-pressed={active} className={`${styles.chip}${active ? ` ${styles.chipOn}` : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

/** A field's details as text, for people who read the fields (the row's line names the rest). */
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
  const current = field.places[Math.min(place, places - 1)];
  return (
    <>
      <SmallText>{current ? `Page ${current.page}${places > 1 ? `, place ${place + 1} of ${places}` : ""}` : null}</SmallText>
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
    </>
  );
}
