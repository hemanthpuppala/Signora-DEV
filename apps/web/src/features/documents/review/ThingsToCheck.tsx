"use client";

import type { components } from "@signora/contracts";
import { useState } from "react";

import { SmallText, TextButton } from "@/shared/ui";

import styles from "./review.module.css";

export type ReviewWarning = components["schemas"]["ReviewWarning"];

/** A field still flagged, as the checklist names it. */
export type LookItem = { id: string; label: string; reason: string };

const FIRST_LOOKS = 5; // more than this and the rest wait behind "Show all"

/**
 * What to look at before approving (Phase 6 §2, §7.1). First the fields that need a look, each by
 * name with why and Show me, from the fields as they are now, so the list shortens as each is
 * settled; then the server's other warnings for the saved fields, each with its way forward: a
 * field's warning shows the field; a party with no place to sign gets "Add signature" (placing one
 * for them) when the person can edit. Never a block; Approve lists them again. With unsaved
 * changes the warnings describe what is saved, and say so.
 */
export function ThingsToCheck({
  warnings,
  looks,
  stale,
  onShow,
  onAddSignature,
}: {
  warnings: readonly ReviewWarning[];
  looks: readonly LookItem[];
  stale: boolean;
  onShow: (fieldId: string) => void;
  onAddSignature: ((partyId: string) => void) | null;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? looks : looks.slice(0, FIRST_LOOKS);
  const others = warnings.filter((warning) => warning.code !== "needs_a_look"); // listed by field above
  return (
    <>
      <ul className={styles.rows} aria-label="Things to check">
        {shown.map((look) => (
          <li key={`look:${look.id}`} className={styles.line}>
            <span className={styles.lookDot} aria-hidden="true" />
            <span className={styles.lookText}>
              <span className={styles.name}>{`${look.label || "Unnamed field"} needs a look`}</span>
              <span className={styles.lookReason}>{look.reason}</span>
            </span>
            <TextButton onClick={() => onShow(look.id)}>Show me</TextButton>
          </li>
        ))}
        {looks.length > FIRST_LOOKS ? (
          <li className={styles.line}>
            <TextButton onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${looks.length}`}</TextButton>
          </li>
        ) : null}
        {others.map((warning) => (
          // One field can have several warnings of one kind (a box over two others): the message
          // names the pair and the page, so it tells them apart.
          <li key={`${warning.code}:${warning.field_id ?? warning.party_id ?? ""}:${warning.message}`} className={styles.line}>
            <span className={styles.name}>{warning.message}</span>
            {warning.field_id ? (
              <TextButton onClick={() => onShow(warning.field_id ?? "")}>Show me</TextButton>
            ) : warning.code === "party_cannot_sign" && warning.party_id && onAddSignature ? (
              <TextButton onClick={() => onAddSignature(warning.party_id ?? "")}>Add signature</TextButton>
            ) : null}
          </li>
        ))}
      </ul>
      {stale && others.length > 0 ? <SmallText>These are for the saved fields. Save to check your changes.</SmallText> : null}
    </>
  );
}
