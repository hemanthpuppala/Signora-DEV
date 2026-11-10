"use client";

import { useState } from "react";

import { Button, Select, TextButton } from "@/shared/ui";

import { HOLD_GROUPS, HOLDS } from "../fields";
import type { DraftParty, FilledBy, Holds } from "./editor";
import styles from "./review.module.css";

/** What the next press on a page makes: a new field, or another place of a field (§5, §7.1). */
export type Tool =
  | { kind: "field"; holds: Holds; filled_by: FilledBy; party_id: string | null }
  | { kind: "place"; fieldId: string; label: string };

/** The types, grouped, as one dropdown's options: each type's name, its group beside it. */
export function typeOptions(keep: (holds: Holds) => boolean = () => true) {
  return HOLD_GROUPS.flatMap((group) =>
    group.holds.filter(keep).map((holds) => ({ value: holds, label: HOLDS[holds], hint: group.label })),
  );
}

/** Every type: what a new field may hold. */
export const TYPE_OPTIONS = typeOptions();

/** Who fills a field, as one dropdown value: a party, the sender, or nobody. */
export function fillerOptions(parties: readonly DraftParty[]) {
  return [
    ...parties.map((party) => ({ value: `party:${party.id}`, label: party.label || "Unnamed party" })),
    { value: "sender", label: "Filled in before sending" },
    { value: "none", label: "Not asked" },
  ];
}

export function filler(value: string): { filled_by: FilledBy; party_id: string | null } {
  if (value.startsWith("party:")) return { filled_by: "role", party_id: value.slice("party:".length) };
  return { filled_by: value === "sender" ? "sender" : "none", party_id: null };
}

/**
 * The open "+ Add field" row (Phase 6 §7.1): a type and who fills it, then "Place on the page".
 * Who fills it starts as the party the list is filtered to. Without room to draw (a phone) the
 * field is put on page 1 and moved with its numbers.
 */
export function AddField({
  parties,
  partyId,
  canDraw,
  onPlace,
}: {
  parties: readonly DraftParty[];
  partyId: string | null;
  canDraw: boolean;
  onPlace: (tool: Extract<Tool, { kind: "field" }>) => void;
}) {
  const [holds, setHolds] = useState<Holds>("signature");
  const [who, setWho] = useState(partyId ? `party:${partyId}` : "none");
  return (
    <div className={styles.addField}>
      <Select label="Type" options={TYPE_OPTIONS} value={holds} onChange={(value) => setHolds(value as Holds)} />
      <Select label="Who fills it" options={fillerOptions(parties)} value={who} onChange={setWho} />
      <div className={styles.actions}>
        <Button compact onClick={() => onPlace({ kind: "field", holds, ...filler(who) })}>
          {canDraw ? "Place on the page" : "Add to page 1"}
        </Button>
      </div>
    </div>
  );
}

/** While placing, what a click on the pages does (pinned over the PDF, where the click goes). */
export function placingMessage(tool: Tool): string {
  const what = tool.kind === "field" ? `the ${HOLDS[tool.holds].toLowerCase()}` : `another place of ${tool.label}`;
  return `Click where ${what} goes, or drag to draw it`;
}

/** The open "+ Add field" row while placing: where to look, and how to stop. */
export function PlacingRow({ onCancel }: { onCancel: () => void }) {
  return (
    <span className={styles.placing}>
      <span>Click on the document to place it.</span>
      <TextButton onClick={onCancel}>Cancel</TextButton>
    </span>
  );
}
