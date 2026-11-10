"use client";

import { useState } from "react";

import { Button, Checkbox, InfoTip, Notice, Select, SmallText, TextField } from "@/shared/ui";

import { HOLD_GROUPS, HOLDS, whoFills } from "../fields";
import { PLACES_HELP } from "./help";
import { PlaceChips } from "./PlaceChips";
import type { PanelEditing } from "./useReview";
import type { Selection } from "../FieldBoxes";
import {
  addParty,
  CONDITIONS,
  mayHold,
  OPTION_MAX,
  onEveryPage,
  PRIVATE,
  setOptionText,
  setRect,
  splitPlace,
  updateField,
  deletePlace,
  type Draft,
  type DraftField,
  type Holds,
  type Rect,
} from "./editor";
import { filler, fillerOptions } from "./AddField";
import { NewParty } from "./PartyList";
import styles from "./review.module.css";

const NEW_PARTY = "new";

/** Who fills, as one select value: a party, the sender, nobody, or a new party (§4). */
function fillerValue(field: DraftField): string {
  if (field.filled_by === "role" && field.party_id) return `party:${field.party_id}`;
  return field.filled_by === "sender" ? "sender" : "none";
}

/** Conditions on offer: every other choice's options and every checkbox ticked. */
function conditionOptions(field: DraftField, draft: Draft) {
  const options = [{ value: "", label: "Always asked" }];
  for (const other of draft.fields) {
    if (other.id === field.id || !CONDITIONS.has(other.holds)) continue;
    if (other.holds === "checkbox") {
      options.push({ value: `${other.id}|checked`, label: `When “${other.label}” is ticked` });
      continue;
    }
    for (const place of other.places) {
      if (!place.option_value) continue;
      options.push({
        value: `${other.id}|${place.option_value}`,
        label: `When “${other.label}” is ${place.option_text ?? place.option_value}`,
      });
    }
  }
  return options;
}

/**
 * One field's form (Phase 6 §4, §5, §7.1), inside its open row in the list. Its type offers only
 * what every one of its boxes may hold (the server's rule, sent with the fields); position and
 * size are numbers, so a box can be placed without a mouse. Every change is one undo step; typing
 * in one box is one.
 */
export function FieldForm({
  field,
  draft,
  place,
  editing,
  onPlace,
  onSelect,
  onDone,
}: {
  field: DraftField;
  draft: Draft;
  place: number;
  editing: PanelEditing;
  onPlace: (place: number) => void;
  onSelect: (selection: Selection) => void;
  onDone: () => void;
}) {
  const { edit } = editing.review;
  const [newParty, setNewParty] = useState(false);
  const current = field.places[Math.min(place, field.places.length - 1)];
  const change = (patch: Parameters<typeof updateField>[2], merge?: string) =>
    edit((draft) => updateField(draft, field.id, patch), merge);

  const allowed = HOLD_GROUPS.flatMap((group) =>
    group.holds
      .filter((holds) => field.places.every((place) => mayHold(editing.allowed, place, holds)))
      .map((holds) => ({ value: holds, label: `${HOLDS[holds]} · ${group.label}` })),
  );
  const fillers = [...fillerOptions(draft.parties), { value: NEW_PARTY, label: "Someone else…" }];
  const conditions = conditionOptions(field, draft);
  const conditionValue = field.depends_on ? `${field.depends_on.field_id}|${field.depends_on.option}` : "";
  const privateByType = PRIVATE.has(field.holds);

  const setFiller = (value: string) => {
    if (value === NEW_PARTY) setNewParty(true);
    else change(filler(value));
  };
  const setNumber = (index: 0 | 1 | 2 | 3, value: string) => {
    if (!current) return;
    const number = Number(value);
    if (!Number.isFinite(number)) return;
    const [x0, y0, x1, y1] = current.rect;
    const size: Rect = [x0, y0, x1 - x0, y1 - y0];
    size[index] = number;
    const rect: Rect = [size[0], size[1], size[0] + size[2], size[1] + size[3]];
    edit((draft) => setRect(draft, current.id, rect, editing.pages, false), `rect:${current.id}`);
  };

  return (
    <div className={styles.form}>
      {field.needs_review ? <Notice tone="warning">{`Needs a look: ${field.needs_review}. Any change clears this.`}</Notice> : null}
      <TextField
        label="Label"
        required
        maxLength={120}
        value={field.label}
        onChange={(event) => change({ label: event.target.value }, `label:${field.id}`)}
      />
      <Select label="Type" options={allowed} value={field.holds} onChange={(value) => change({ holds: value as Holds })} />
      {field.holds === "other" ? (
        <>
          <TextField
            label="Type, in your words"
            hint="Matter number, Stamp…"
            required
            maxLength={60}
            value={field.holds_label ?? ""}
            onChange={(event) => change({ holds_label: event.target.value }, `holds-label:${field.id}`)}
          />
          <Checkbox checked={field.sensitive} onChange={(event) => change({ sensitive: event.target.checked })}>
            Private: shown only to whoever fills it
          </Checkbox>
        </>
      ) : null}
      <Select label="Who fills it" options={fillers} value={newParty ? NEW_PARTY : fillerValue(field)} onChange={setFiller} />
      {newParty ? (
        <NewParty
          onAdd={(party) => {
            edit((draft) => {
              const added = addParty(draft, party);
              return updateField(added.draft, field.id, { filled_by: "role", party_id: added.partyId });
            });
            setNewParty(false);
          }}
          onCancel={() => setNewParty(false)}
        />
      ) : null}
      {privateByType ? <SmallText>{`Private: shown only to ${whoFills(field, draft.parties)}.`}</SmallText> : null}
      <Checkbox checked={field.required} onChange={(event) => change({ required: event.target.checked })}>
        Required
      </Checkbox>
      {conditions.length > 1 ? (
        <Select
          label="Asked"
          options={conditions}
          value={conditionValue}
          onChange={(value) => {
            const [fieldId = "", option = ""] = value.split("|");
            change({ depends_on: value ? { field_id: fieldId, option } : null });
          }}
        />
      ) : null}
      {field.holds === "choice" ? (
        <fieldset className={styles.fates}>
          <legend>Options</legend>
          {field.places.map((option, index) => (
            <TextField
              key={option.id}
              label={`Option ${index + 1}`}
              maxLength={OPTION_MAX}
              value={option.option_text ?? option.option_value ?? ""}
              onChange={(event) => {
                const text = event.target.value;
                edit((draft) => setOptionText(draft, option.id, text), `option:${option.id}`);
              }}
            />
          ))}
        </fieldset>
      ) : null}

      <section className={styles.places} aria-label="Places">
        <div className={styles.groupHead}>
          <p className={styles.groupTitle}>{field.places.length > 1 ? `Places · ${field.places.length}` : "Place"}</p>
          <InfoTip label="places">{PLACES_HELP}</InfoTip>
        </div>
        <PlaceChips places={field.places} place={place} onPlace={onPlace} choice={field.holds === "choice"} />
        <div className={styles.toolRow}>
          {editing.canDraw ? (
            <Button variant="quiet" compact icon="plus" onClick={() => editing.onAddPlace(field.id)}>
              Add a place
            </Button>
          ) : null}
          {current && editing.pages.length > 1 ? (
            <Button variant="quiet" compact icon="pages" onClick={() => edit((draft) => onEveryPage(draft, current.id, editing.pages))}>
              On every page
            </Button>
          ) : null}
        </div>
        {current && field.places.length > 1 ? (
          <div className={styles.toolRow} role="group" aria-label={`Place ${place + 1}`}>
            <Button
              variant="quiet"
              compact
              icon="split"
              onClick={() => {
                let made: string | null = null;
                edit((draft) => {
                  const split = splitPlace(draft, current.id);
                  made = split.fieldId;
                  return split.draft;
                });
                if (made) onSelect({ kind: "field", id: made, place: 0 });
              }}
            >
              Make separate field
            </Button>
            <Button
              variant="quiet"
              compact
              icon="close"
              onClick={() => {
                edit((draft) => deletePlace(draft, current.id));
                onPlace(Math.max(0, place - 1));
              }}
            >
              Remove place
            </Button>
          </div>
        ) : null}
        {current ? (
          <details className={styles.more}>
            <summary>{`Position and size · page ${current.page}`}</summary>
            <div className={styles.numbers}>
              {(["Left", "Top", "Width", "Height"] as const).map((name, index) => {
                const [x0, y0, x1, y1] = current.rect;
                const values = [x0, y0, x1 - x0, y1 - y0];
                return (
                  <TextField
                    key={name}
                    label={name}
                    type="number"
                    step="1"
                    value={String(Math.round((values[index] ?? 0) * 100) / 100)}
                    onChange={(event) => setNumber(index as 0 | 1 | 2 | 3, event.target.value)}
                  />
                );
              })}
            </div>
            <SmallText>In points from the page&apos;s top left. Dragging the box on the document does the same.</SmallText>
          </details>
        ) : null}
      </section>
      <div className={styles.formEnd}>
        <Button variant="destructive" compact icon="trash" onClick={() => editing.onDeleteField(field.id)}>
          Delete field
        </Button>
        <Button variant="quiet" compact onClick={onDone}>
          Done
        </Button>
      </div>
    </div>
  );
}
