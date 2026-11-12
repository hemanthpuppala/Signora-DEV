"use client";

import { useEffect, useMemo, useState } from "react";

import { Chip, ChipGroup, ExpandableList, ExpandableRow, HeadAction, Notice, SearchField, Section, SmallText } from "@/shared/ui";

import { HOLDS, toneOf, whoFills, type PartyRef, type VersionFields } from "./fields";
import type { Selection } from "./FieldBoxes";
import styles from "./fields.module.css";
import { AddField, PlacingRow } from "./review/AddField";
import { markChecked, needingALook, type Draft, type DraftField } from "./review/editor";
import { FieldForm } from "./review/FieldForm";
import { FIELDS_HELP, THINGS_TO_CHECK_HELP, WHO_SIGNS_HELP } from "./review/help";
import { PartyList } from "./review/PartyList";
import { PlaceChips } from "./review/PlaceChips";
import type { LookStep } from "./review/NeedsALook";
import { NeedsALook } from "./review/NeedsALook";
import { ThingsToCheck } from "./review/ThingsToCheck";
import type { PanelEditing } from "./review/useReview";

const STEPS = ["Read the document", "Finding who fills each field", "Checking"] as const;
const STEP_OF_STAGE: Record<string, number> = { read: 0, ai: 1, derive: 2, store: 2, done: 3 };
const ADD_ROW = "add-field";

export type Filter = { kind: "all" } | { kind: "party"; id: string } | { kind: "sender" } | { kind: "look" };
type Row = { id: string; field: DraftField; depth: number };

/** Brings the list with the chosen field into view, smoothly unless the person asked for less motion. */
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
  follow = true,
  onEdit,
}: {
  view: VersionFields;
  draft: Draft;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
  onClear: () => void;
  filter: Filter;
  onFilter: (filter: Filter) => void;
  editing: PanelEditing | null;
  /** Bring the chosen field's row into view. Off when the list is under the document and the field
   * was chosen on the page (a phone): the person stays with the box they touched. */
  follow?: boolean;
  /** Start editing an approved version's fields, from here: where the panel is under the document
   * (a narrow screen) the action is in the panel's first title line, by what it edits. */
  onEdit?: (() => void) | undefined;
}) {
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const parties: PartyRef[] = draft.parties;
  const byId = useMemo(() => new Map(draft.fields.map((field) => [field.id, field])), [draft.fields]);
  const flagged = useMemo(() => needingALook(draft), [draft]);
  // "Needs a look" with none left shows every field, not an empty list.
  const active = useMemo<Filter>(() => (filter.kind === "look" && flagged.length === 0 ? { kind: "all" } : filter), [filter, flagged.length]);
  // A field chosen on the PDF (or from a warning) opens in the list, which comes into view; the
  // list itself brings the open row to its top.
  // A closed Fields section opens for it first: a closed section has nothing to bring into view.
  const rowId = selected ? (selected.kind === "field" ? `field-${selected.id}` : `pending-${selected.id}`) : null;
  const [fieldsOpen, setFieldsOpen] = useState(true);
  const [openedFor, setOpenedFor] = useState(rowId);
  if (rowId !== openedFor) {
    setOpenedFor(rowId);
    if (rowId) setFieldsOpen(true);
  }
  useEffect(() => {
    const list = rowId ? document.getElementById(rowId)?.parentElement : null;
    if (list && follow) bringIntoView(list);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a new choice scrolls, not a change of ``follow``
  }, [rowId]);

  const rows = useMemo<Row[]>(() => {
    const query = search.trim().toLowerCase();
    const shown = (field: DraftField) =>
      (active.kind === "all" ||
        (active.kind === "look" && Boolean(field.needs_review)) ||
        (active.kind === "sender" && field.filled_by === "sender") ||
        (active.kind === "party" && field.filled_by === "role" && field.party_id === active.id)) &&
      (!query || field.label.toLowerCase().includes(query));
    const ordered = [...draft.fields].sort((a, b) => Number(Boolean(b.needs_review)) - Number(Boolean(a.needs_review)));
    if (query || active.kind !== "all") {
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
  }, [draft.fields, byId, active, search]);

  if (view.status === "detecting") {
    const step = STEP_OF_STAGE[view.stage ?? "read"] ?? 0;
    return (
      <Section title="Fields" collapsible open={fieldsOpen} onOpenChange={setFieldsOpen}>
        <ol className={styles.steps} aria-label="Finding fields">
          {STEPS.map((label, index) => (
            <li key={label} className={index < step ? styles.done : index === step ? styles.running : styles.next}>
              <span aria-hidden="true">{index < step ? "✓" : index === step ? "●" : "○"}</span>
              <span>{index === 0 && step > 0 ? `${label}: ${placesFound(view)}` : label}</span>
            </li>
          ))}
        </ol>
        {view.pending.length > 0 ? (
          <ExpandableList label="Places found" scrollable>
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

  /** A flagged field's place in the checklist: Next goes on to the following one; Looks right
   * accepts it as found and goes on, or closes it when it was the last. */
  const lookStep = (field: DraftField): LookStep | null => {
    const index = flagged.findIndex((one) => one.id === field.id);
    if (index < 0) return null;
    const go = (next: DraftField | undefined) => (next ? onSelect({ kind: "field", id: next.id, place: 0 }) : onClear());
    return {
      position: index + 1,
      total: flagged.length,
      onNext: () => go(flagged[(index + 1) % flagged.length]),
      onLooksRight: editing
        ? () => {
            editing.review.edit((current) => markChecked(current, field.id));
            const rest = flagged.filter((one) => one.id !== field.id);
            go(rest[index] ?? rest[0]);
          }
        : null,
    };
  };

  return (
    <>
      {inReview && (view.warnings.length > 0 || flagged.length > 0) ? (
        <Section title="Things to check" info={THINGS_TO_CHECK_HELP} collapsible>
          <ThingsToCheck
            warnings={view.warnings}
            looks={flagged.map((field) => ({ id: field.id, label: field.label, reason: field.needs_review ?? "" }))}
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
      <Section
        title="Who signs"
        info={WHO_SIGNS_HELP}
        action={onEdit ? <HeadAction icon="edit" label="Edit fields" onClick={onEdit} /> : undefined}
        collapsible
      >
        <PartyList parties={draft.parties} fields={draft.fields} sender={sender} edit={editing ? editing.review.edit : null} />
      </Section>
      <Section title={`Fields · ${draft.fields.length}`} info={FIELDS_HELP} collapsible open={fieldsOpen} onOpenChange={setFieldsOpen}>
        {view.flags.no_fields && draft.fields.length === 0 ? (
          <Notice>{editing ? "We couldn't find places to fill or sign. Add them below." : "We couldn't find places to fill or sign."}</Notice>
        ) : null}
        {view.found_again_failed ? (
          <Notice tone="warning">{`${view.found_again_failed}. These are the fields found before.`}</Notice>
        ) : null}
        {draft.fields.length > 0 ? (
          <>
            <ChipGroup label="Show fields of">
              <Chip selected={filter.kind === "all"} onClick={() => onFilter({ kind: "all" })}>
                All
              </Chip>
              {parties.map((party) => (
                <Chip
                  key={party.id}
                  selected={filter.kind === "party" && filter.id === party.id}
                  onClick={() => onFilter({ kind: "party", id: party.id })}
                >
                  {party.label || "Unnamed party"}
                </Chip>
              ))}
              {sender > 0 ? (
                <Chip selected={filter.kind === "sender"} onClick={() => onFilter({ kind: "sender" })}>
                  Before sending
                </Chip>
              ) : null}
              {flagged.length > 0 ? (
                <Chip selected={active.kind === "look"} onClick={() => onFilter({ kind: "look" })}>
                  {`Needs a look · ${flagged.length}`}
                </Chip>
              ) : null}
            </ChipGroup>
            <SearchField label="Find a field" value={search} onChange={(event) => setSearch(event.target.value)} />
          </>
        ) : null}
        <ExpandableList label="Fields" scrollable>
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
                <PlacingRow touch={editing.touch} onCancel={editing.cancelPlacing} />
              ) : (
                <AddField
                  parties={draft.parties}
                  partyId={filteredParty}
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
                title={
                  <>
                    {row.field.label || "Unnamed field"}
                    {row.field.needs_review ? <span className={styles.lookDot} aria-hidden="true" /> : null}
                  </>
                }
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
                      look={lookStep(row.field)}
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
                      look={lookStep(row.field)}
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

/** A field's details as text, for people who read the fields (the row's line names the rest). */
function FieldDetails({
  field,
  parties,
  byId,
  place,
  look,
  onPlace,
}: {
  field: DraftField;
  parties: readonly PartyRef[];
  byId: ReadonlyMap<string, DraftField>;
  place: number;
  look: LookStep | null;
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
      {field.needs_review ? <NeedsALook reason={field.needs_review} step={look} /> : null}
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
      {places > 1 ? <PlaceChips places={field.places} place={place} onPlace={onPlace} choice={field.holds === "choice"} /> : null}
    </>
  );
}
