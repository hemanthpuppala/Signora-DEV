"use client";

import { useState, type FormEvent } from "react";

import { Button, Dialog, Radio, Select, TextButton, TextField } from "@/shared/ui";

import { toneOf } from "../fields";
import fieldStyles from "../fields.module.css";
import {
  addParty,
  MAX_PARTIES,
  moveParty,
  removeParty,
  updateParty,
  type DraftField,
  type DraftParty,
  type PartyFate,
  type PartyKind,
  type Edit,
} from "./editor";
import styles from "./review.module.css";


/** "countersigns", or an Other kind's own words ("Witness"). */
function kindWords(party: DraftParty): string | null {
  if (party.kind_label) return party.kind_label;
  return party.kind === "countersigner" ? "countersigns" : null;
}

/**
 * "Who signs" (Phase 6 §3): each party with its tone and field count, and the fields filled in
 * before sending. Editing adds rename, order within its group (signers sign first), remove (asking
 * what becomes of its fields) and a new party.
 */
export function PartyList({
  parties,
  fields,
  sender,
  edit,
}: {
  parties: readonly DraftParty[];
  fields: readonly DraftField[];
  sender: number;
  edit: Edit | null;
}) {
  const [removing, setRemoving] = useState<DraftParty | null>(null);
  const [adding, setAdding] = useState(false);
  const count = (id: string) => fields.filter((field) => field.filled_by === "role" && field.party_id === id).length;
  if (parties.length === 0 && sender === 0 && !edit) return null;
  return (
    <>
      <ul className={fieldStyles.parties} aria-label="Who signs">
        {parties.map((party, index) => {
          const n = count(party.id);
          const before = parties[index - 1];
          const after = parties[index + 1];
          return (
            <li key={party.id}>
              <span className={`${fieldStyles.dot} ${fieldStyles[toneOf({ filled_by: "role", party_id: party.id }, parties)]}`} aria-hidden="true" />
              {edit ? (
                <input
                  className={styles.inlineName}
                  aria-label={`Name of ${party.label || "this party"}`}
                  value={party.label}
                  maxLength={80}
                  onChange={(event) => {
                    const label = event.target.value;
                    edit((draft) => updateParty(draft, party.id, { label }), `party-label:${party.id}`);
                  }}
                />
              ) : (
                <span className={fieldStyles.label}>{party.label}</span>
              )}
              {kindWords(party) ? <span className={fieldStyles.meta}>{kindWords(party)}</span> : null}
              <span className={fieldStyles.count}>{`${n} ${n === 1 ? "field" : "fields"}`}</span>
              {edit ? (
                <span className={styles.rowTools}>
                  <TextButton
                    aria-label={`Move ${party.label} up`}
                    disabled={before?.kind !== party.kind}
                    onClick={() => edit((draft) => moveParty(draft, party.id, -1))}
                  >
                    ↑
                  </TextButton>
                  <TextButton
                    aria-label={`Move ${party.label} down`}
                    disabled={after?.kind !== party.kind}
                    onClick={() => edit((draft) => moveParty(draft, party.id, 1))}
                  >
                    ↓
                  </TextButton>
                  <TextButton
                    aria-label={`Remove ${party.label}`}
                    onClick={() =>
                      n === 0 ? edit((draft) => removeParty(draft, party.id, { kind: "none" })) : setRemoving(party)
                    }
                  >
                    ✕
                  </TextButton>
                </span>
              ) : null}
            </li>
          );
        })}
        {sender > 0 ? (
          <li>
            <span className={`${fieldStyles.dot} ${fieldStyles.sender}`} aria-hidden="true" />
            <span className={fieldStyles.label}>Filled in before sending</span>
            <span className={fieldStyles.count}>{`${sender} ${sender === 1 ? "field" : "fields"}`}</span>
          </li>
        ) : null}
      </ul>
      {edit && !adding ? (
        parties.length < MAX_PARTIES ? (
          <TextButton onClick={() => setAdding(true)}>+ Add party</TextButton>
        ) : null
      ) : null}
      {edit && adding ? (
        <NewParty
          onAdd={(party) => {
            edit((draft) => addParty(draft, party).draft);
            setAdding(false);
          }}
          onCancel={() => setAdding(false)}
        />
      ) : null}
      {edit && removing ? (
        <RemoveParty
          party={removing}
          others={parties.filter((party) => party.id !== removing.id)}
          fields={count(removing.id)}
          onRemove={(fate) => {
            edit((draft) => removeParty(draft, removing.id, fate));
            setRemoving(null);
          }}
          onCancel={() => setRemoving(null)}
        />
      ) : null}
    </>
  );
}

const KINDS = [
  { value: "signer", label: "Signer" },
  { value: "countersigner", label: "Countersigner" },
  { value: "other", label: "Other…" },
];
const SIGNS_LIKE = [
  { value: "signer", label: "Signs like a signer" },
  { value: "countersigner", label: "Signs like a countersigner" },
];

/** A party's name and kind; Other is typed words on one of the two ways of signing (§3). */
export function NewParty({
  onAdd,
  onCancel,
  initialName = "",
}: {
  onAdd: (party: Omit<DraftParty, "id">) => void;
  onCancel: () => void;
  initialName?: string;
}) {
  const [label, setLabel] = useState(initialName);
  const [kind, setKind] = useState("signer");
  const [kindLabel, setKindLabel] = useState("");
  const [signsLike, setSignsLike] = useState<PartyKind>("signer");
  const other = kind === "other";
  const ready = label.trim() !== "" && (!other || kindLabel.trim() !== "");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    onAdd({
      label: label.trim(),
      kind: other ? signsLike : (kind as PartyKind),
      kind_label: other ? kindLabel.trim() : null,
    });
  };
  return (
    <form className={styles.inlineForm} onSubmit={submit} aria-label="New party">
      <TextField label="Name" required maxLength={80} value={label} onChange={(event) => setLabel(event.target.value)} />
      <Select label="Kind" options={KINDS} value={kind} onChange={setKind} />
      {other ? (
        <>
          <TextField
            label="Kind, in your words"
            hint="Witness, Guarantor…"
            required
            maxLength={40}
            value={kindLabel}
            onChange={(event) => setKindLabel(event.target.value)}
          />
          <Select label="When they sign" options={SIGNS_LIKE} value={signsLike} onChange={(value) => setSignsLike(value as PartyKind)} />
        </>
      ) : null}
      <div className={styles.actions}>
        <Button type="submit" variant="quiet" compact disabled={!ready}>
          Add party
        </Button>
        <TextButton onClick={onCancel}>Cancel</TextButton>
      </div>
    </form>
  );
}

/** Removing a party asks what becomes of its fields (§3): moved (merging parties), not asked, or deleted. */
function RemoveParty({
  party,
  others,
  fields,
  onRemove,
  onCancel,
}: {
  party: DraftParty;
  others: readonly DraftParty[];
  fields: number;
  onRemove: (fate: PartyFate) => void;
  onCancel: () => void;
}) {
  const [choice, setChoice] = useState<"move" | "none" | "delete">(others.length > 0 ? "move" : "none");
  const [to, setTo] = useState<string | null>(others[0]?.id ?? null);
  const noun = `${fields} ${fields === 1 ? "field" : "fields"}`;
  const fate: PartyFate | null =
    choice === "move" ? (to ? { kind: "move", to } : null) : choice === "none" ? { kind: "none" } : { kind: "delete" };
  return (
    <Dialog
      title={`Remove ${party.label}?`}
      onClose={onCancel}
      actions={
        <>
          <Button variant={choice === "delete" ? "destructive" : "primary"} disabled={!fate} onClick={() => fate && onRemove(fate)}>
            Remove party
          </Button>
          <TextButton onClick={onCancel}>Cancel</TextButton>
        </>
      }
    >
      <fieldset className={styles.fates}>
        <legend>{`What happens to their ${noun}?`}</legend>
        {others.length > 0 ? (
          <Radio name="fate" checked={choice === "move"} onChange={() => setChoice("move")}>
            Give them to another party
          </Radio>
        ) : null}
        {choice === "move" && others.length > 0 ? (
          <Select
            label="Party"
            options={others.map((other) => ({ value: other.id, label: other.label }))}
            value={to}
            onChange={setTo}
          />
        ) : null}
        <Radio name="fate" checked={choice === "none"} onChange={() => setChoice("none")}>
          Keep them, not asked of anyone
        </Radio>
        <Radio name="fate" checked={choice === "delete"} onChange={() => setChoice("delete")}>
          Delete them
        </Radio>
      </fieldset>
    </Dialog>
  );
}
