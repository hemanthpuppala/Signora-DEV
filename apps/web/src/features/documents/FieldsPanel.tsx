"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { Notice, SearchField, SmallText, TextButton } from "@/shared/ui";

import { HOLDS, toneOf, whoFills, type FieldView, type RoleView, type VersionFields } from "./fields";
import type { Selection } from "./FieldBoxes";
import styles from "./fields.module.css";

const STEPS = ["Read the document", "Finding who fills each field", "Checking"] as const;
const STEP_OF_STAGE: Record<string, number> = { read: 0, ai: 1, derive: 2, store: 2, done: 3 };

type Filter = { kind: "all" } | { kind: "role"; slug: string } | { kind: "sender" };
type Row = { key: string; field: FieldView; depth: number; under?: string };

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
function condition(field: FieldView, byKey: ReadonlyMap<string, FieldView>): string | null {
  if (!field.depends_on) return null;
  const parent = byKey.get(field.depends_on.key);
  if (!parent) return null;
  if (field.depends_on.option === "checked") return `Only when “${parent.label}” is ticked`;
  const place = parent.placements.find((p) => p.option_value === field.depends_on?.option);
  return `Only when “${place?.option_text ?? field.depends_on.option}” is chosen`;
}

/**
 * Every field of a version, linked with the PDF (Phase 5 LLD §6.2-6.4): pick one here and the
 * viewer brings it into view; pick a box there and it is chosen here. Fields that need a look come
 * first; choices list their options with the fields that only apply under each. While the AI works,
 * the places already found are listed and drawn. Read-only: Phase 6 adds editing and approval.
 */
export function FieldsPanel({
  view,
  selected,
  onSelect,
}: {
  view: VersionFields;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  const [filter, setFilter] = useState<Filter>({ kind: "all" });
  const [search, setSearch] = useState("");
  const roles = view.roles;
  const byKey = useMemo(() => new Map(view.fields.map((field) => [field.key, field])), [view.fields]);
  // A field chosen on the PDF (or with the keys) is brought into view in the list too.
  const listRef = useRef<HTMLUListElement>(null);
  const rowId = selected ? (selected.kind === "field" ? `field-${selected.key}` : `pending-${selected.id}`) : null;
  useEffect(() => {
    const list = listRef.current;
    const row = rowId ? [...(list?.children ?? [])].find((child) => child.id === rowId) : undefined;
    if (list && row) showWithin(list, row);
  }, [rowId]);

  const rows = useMemo<Row[]>(() => {
    const query = search.trim().toLowerCase();
    const shown = (field: FieldView) =>
      (filter.kind === "all" ||
        (filter.kind === "sender" && field.filled_by === "sender") ||
        (filter.kind === "role" && field.role === filter.slug)) &&
      (!query || field.label.toLowerCase().includes(query));
    const ordered = [...view.fields].sort((a, b) => Number(Boolean(b.needs_review)) - Number(Boolean(a.needs_review)));
    if (query || filter.kind !== "all") {
      return ordered.filter(shown).map((field) => ({ key: field.key, field, depth: 0 }));
    }
    // A tree: a field that applies under an option sits under its choice.
    const children = new Map<string, FieldView[]>();
    for (const field of ordered) {
      if (field.depends_on && byKey.has(field.depends_on.key)) {
        children.set(field.depends_on.key, [...(children.get(field.depends_on.key) ?? []), field]);
      }
    }
    const out: Row[] = [];
    const visit = (field: FieldView, depth: number) => {
      out.push({ key: field.key, field, depth });
      for (const child of children.get(field.key) ?? []) visit(child, depth + 1);
    };
    for (const field of ordered) if (!field.depends_on || !byKey.has(field.depends_on.key)) visit(field, 0);
    return out;
  }, [view.fields, byKey, filter, search]);

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

  const chosen = selected?.kind === "field" ? byKey.get(selected.key) : undefined;
  const parties = roles.length;
  const sender = view.fields.filter((field) => field.filled_by === "sender").length;
  const needsLook = view.fields.filter((field) => field.needs_review).length;

  const move = (event: KeyboardEvent<HTMLUListElement>) => {
    const index = rows.findIndex((row) => row.key === chosen?.key);
    const next =
      event.key === "ArrowDown" ? Math.min(index + 1, rows.length - 1) : event.key === "ArrowUp" ? Math.max(index - 1, 0) : null;
    if (event.key === "Enter" && chosen) {
      event.preventDefault();
      onSelect({ kind: "field", key: chosen.key, place: 0 });
    } else if (next !== null && rows[next]) {
      event.preventDefault();
      onSelect({ kind: "field", key: rows[next].key, place: 0 });
    }
  };

  return (
    <div className={styles.panel}>
      {view.fields.length > 0 ? (
        <p className={styles.headline}>
          {`${view.fields.length} ${view.fields.length === 1 ? "field" : "fields"} for ${parties} ${parties === 1 ? "party" : "parties"}`}
        </p>
      ) : null}
      {view.flags.no_fields ? (
        <Notice>We couldn&apos;t find places to fill or sign. Add them in review.</Notice>
      ) : null}
      {needsLook > 0 ? (
        <Notice tone="warning">{`${needsLook} ${needsLook === 1 ? "field needs" : "fields need"} a look. They are listed first.`}</Notice>
      ) : null}
      {view.flags.addressed_to_ai ? (
        <Notice tone="warning">This document contains text addressed to an AI. Check its fields with care.</Notice>
      ) : null}
      {view.flags.xfa ? (
        <Notice tone="warning">This PDF is an XFA form: what Acrobat shows may differ from these fields.</Notice>
      ) : null}
      {view.flags.already_signed ? (
        <Notice tone="warning">This PDF is already signed: filling it in breaks that signature.</Notice>
      ) : null}
      {view.found_again_failed ? (
        <Notice tone="warning">{`${view.found_again_failed}. These are the fields found before.`}</Notice>
      ) : null}
      {roles.length > 0 || sender > 0 ? (
        <ul className={styles.parties} aria-label="Who signs">
          {roles.map((role) => (
            <li key={role.slug}>
              <span className={`${styles.dot} ${styles[toneOf({ filled_by: "role", role: role.slug }, roles)]}`} aria-hidden="true" />
              <span className={styles.label}>{role.label}</span>
              {role.kind === "countersigner" ? <span className={styles.meta}>countersigns</span> : null}
              <span className={styles.count}>{`${role.field_count} ${role.field_count === 1 ? "field" : "fields"}`}</span>
            </li>
          ))}
          {sender > 0 ? (
            <li>
              <span className={`${styles.dot} ${styles.sender}`} aria-hidden="true" />
              <span className={styles.label}>Filled in before sending</span>
              <span className={styles.count}>{`${sender} ${sender === 1 ? "field" : "fields"}`}</span>
            </li>
          ) : null}
        </ul>
      ) : null}
      {view.fields.length > 0 ? (
        <>
          <div className={styles.filters} role="group" aria-label="Show fields of">
            <FilterChip active={filter.kind === "all"} onClick={() => setFilter({ kind: "all" })}>
              All
            </FilterChip>
            {roles.map((role) => (
              <FilterChip
                key={role.slug}
                active={filter.kind === "role" && filter.slug === role.slug}
                onClick={() => setFilter({ kind: "role", slug: role.slug })}
              >
                {role.label}
              </FilterChip>
            ))}
            {sender > 0 ? (
              <FilterChip active={filter.kind === "sender"} onClick={() => setFilter({ kind: "sender" })}>
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
            aria-activedescendant={chosen ? `field-${chosen.key}` : undefined}
            onKeyDown={move}
          >
            {rows.map((row) => (
              <li
                key={row.key}
                id={`field-${row.key}`}
                role="option"
                aria-selected={chosen?.key === row.key}
                className={`${styles.item}${chosen?.key === row.key ? ` ${styles.selected}` : ""}`}
                style={{ paddingLeft: 12 + row.depth * 16 }}
                onClick={() => onSelect({ kind: "field", key: row.key, place: 0 })}
              >
                <span className={`${styles.dot} ${styles[toneOf(row.field, roles)]}`} aria-hidden="true" />
                <span className={styles.label}>{row.field.label}</span>
                <span className={styles.meta}>
                  {[
                    whoFills(row.field, roles),
                    HOLDS[row.field.holds],
                    row.field.required ? "Required" : "Optional",
                    row.field.placements.length > 1 ? `${row.field.placements.length} places` : null,
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
              roles={roles}
              byKey={byKey}
              place={selected.place}
              onPlace={(place) => onSelect({ kind: "field", key: chosen.key, place })}
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
  roles,
  byKey,
  place,
  onPlace,
}: {
  field: FieldView;
  roles: readonly RoleView[];
  byKey: ReadonlyMap<string, FieldView>;
  place: number;
  onPlace: (place: number) => void;
}) {
  const places = field.placements.length;
  const options = field.holds === "choice" ? field.placements : [];
  const when = condition(field, byKey);
  // The list's row already names the field and who fills it: this says only what the row can't.
  if (!when && !field.sensitive && !field.needs_review && options.length === 0 && places <= 1) return null;
  return (
    <section className={styles.details} aria-label={`More about ${field.label}`} aria-live="polite">
      {when ? <SmallText>{when}</SmallText> : null}
      {field.sensitive ? (
        <SmallText>{`Private to ${whoFills(field, roles)}: shown to nobody else`}</SmallText>
      ) : null}
      {field.needs_review ? <Notice tone="warning">{`Needs a look: ${field.needs_review}.`}</Notice> : null}
      {options.length > 0 ? (
        <ul className={styles.options} aria-label="Options">
          {options.map((option) => {
            const inside = [...byKey.values()].filter(
              (other) => other.depends_on?.key === field.key && other.depends_on.option === option.option_value,
            );
            return (
              <li key={`${option.page}-${option.rect.join(",")}`}>
                <span aria-hidden="true">( ) </span>
                {option.option_text ?? option.option_value}
                {inside.length > 0 ? <span className={styles.meta}>{` → also asks ${inside.map((f) => f.label).join(", ")}`}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {places > 1 ? (
        <div className={styles.stepper}>
          <TextButton aria-label="Previous place" disabled={place <= 0} onClick={() => onPlace(place - 1)}>
            ‹
          </TextButton>
          <span>{`Place ${place + 1} of ${places}`}</span>
          <TextButton aria-label="Next place" disabled={place >= places - 1} onClick={() => onPlace(place + 1)}>
            ›
          </TextButton>
        </div>
      ) : null}
    </section>
  );
}
