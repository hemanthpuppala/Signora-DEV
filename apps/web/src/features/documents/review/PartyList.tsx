"use client";

import { useState, type FormEvent } from "react";

import { Button, Dialog, IconButton, Radio, Select, TextButton, TextField } from "@/shared/ui";

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
  type Edit,
  type PartyFate,
  type PartyKind,
} from "./editor";
import styles from "./review.module.css";

/** How a party signs, in words: "Signer", "Countersigner", or an Other kind's own ("Witness"). */
function kindWords(party: DraftParty): string {
  return party.kind_label ?? (party.kind === "countersigner" ? "Countersigner" : "Signer");
}

/**
 * "Who signs" (Phase 6 §3, §7.1): each party as a line of text (tone, name, how they sign, field
 * count) and the fields filled in before sending. With edit access a pencil turns one row into
 * its editor: name, kind, order within its group (signers sign first), remove (asking what
 * becomes of its fields).
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
  const [editingId, setEditingId] = useState<string | null>(null);
  const [removing, setRemoving] = useState<DraftParty | null>(null);
  const [adding, setAdding] = useState(false);
  const count = (id: string) => fields.filter((field) => field.filled_by === "role" && field.party_id === id).length;
  const fieldsWord = (n: number) => `${n} ${n === 1 ? "field" : "fields"}`;

  return (
    <>
      {parties.length === 0 && sender === 0 ? <p className={styles.empty}>No parties yet.</p> : null}
      <ul className={styles.rows} aria-label="Who signs">
        {parties.map((party, index) => {
          const n = count(party.id);
          const tone = <span className={`${fieldStyles.dot} ${fieldStyles[toneOf({ filled_by: "role", party_id: party.id }, parties)]}`} aria-hidden="true" />;
          if (edit && editingId === party.id) {
            const before = parties[index - 1];
            const after = parties[index + 1];
            return (
              <li key={party.id} className={styles.editingRow}>
                <PartyEditor party={party} edit={edit} />
                <div className={styles.actions}>
                  <TextButton disabled={before?.kind !== party.kind} onClick={() => edit((draft) => moveParty(draft, party.id, -1))}>
                    Move up
                  </TextButton>
                  <TextButton disabled={after?.kind !== party.kind} onClick={() => edit((draft) => moveParty(draft, party.id, 1))}>
                    Move down
                  </TextButton>
                  <TextButton
                    onClick={() => {
                      if (n === 0) {
                        edit((draft) => removeParty(draft, party.id, { kind: "none" }));
                        setEditingId(null);
                      } else setRemoving(party);
                    }}
                  >
                    Remove
                  </TextButton>
                  <Button variant="quiet" compact onClick={() => setEditingId(null)}>
                    Done
                  </Button>
                </div>
              </li>
            );
          }
          return (
            <li key={party.id} className={styles.line}>
              {tone}
              <span className={styles.name}>{party.label || "Unnamed party"}</span>
              <span className={styles.kind}>{kindWords(party)}</span>
              <span className={styles.number}>{fieldsWord(n)}</span>
              {edit ? <IconButton icon="edit" label={`Edit ${party.label || "party"}`} onClick={() => setEditingId(party.id)} /> : null}
            </li>
          );
        })}
        {sender > 0 ? (
          <li className={styles.line}>
            <span className={`${fieldStyles.dot} ${fieldStyles.sender}`} aria-hidden="true" />
            <span className={styles.name}>Filled in before sending</span>
            <span className={styles.number}>{fieldsWord(sender)}</span>
          </li>
        ) : null}
      </ul>
      {edit && adding ? (
        <NewParty
          onAdd={(party) => {
            edit((draft) => addParty(draft, party).draft);
            setAdding(false);
          }}
          onCancel={() => setAdding(false)}
        />
      ) : null}
      {edit && !adding && parties.length < MAX_PARTIES ? (
        <div>
          <TextButton onClick={() => setAdding(true)}>+ Add party</TextButton>
        </div>
      ) : null}
      {edit && removing ? (
        <RemoveParty
          party={removing}
          others={parties.filter((party) => party.id !== removing.id)}
          fields={count(removing.id)}
          onRemove={(fate) => {
            edit((draft) => removeParty(draft, removing.id, fate));
            setRemoving(null);
            setEditingId(null);
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

/** A party's name and kind, changed as you type (one undo step per box). */
function PartyEditor({ party, edit }: { party: DraftParty; edit: Edit }) {
  const [other, setOther] = useState(party.kind_label !== null);
  return (
    <>
      <TextField
        label="Name"
        required
        maxLength={80}
        value={party.label}
        onChange={(event) => {
          const label = event.target.value;
          edit((draft) => updateParty(draft, party.id, { label }), `party-label:${party.id}`);
        }}
      />
      <Select
        label="Kind"
        options={KINDS}
        value={other ? "other" : party.kind}
        onChange={(value) => {
          if (value === "other") {
            setOther(true);
            edit((draft) => updateParty(draft, party.id, { kind_label: party.kind_label ?? "" }));
          } else {
            setOther(false);
            edit((draft) => updateParty(draft, party.id, { kind: value as PartyKind, kind_label: null }));
          }
        }}
      />
      {other ? (
        <>
          <TextField
            label="Kind, in your words"
            hint="Witness, Guarantor…"
            required
            maxLength={40}
            value={party.kind_label ?? ""}
            onChange={(event) => {
              const kind_label = event.target.value;
              edit((draft) => updateParty(draft, party.id, { kind_label }), `party-kind:${party.id}`);
            }}
          />
          <Select
            label="When they sign"
            options={SIGNS_LIKE}
            value={party.kind}
            onChange={(value) => edit((draft) => updateParty(draft, party.id, { kind: value as PartyKind }))}
          />
        </>
      ) : null}
    </>
  );
}

/** A new party's name and kind; Other is typed words on one of the two ways of signing (§3). */
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
