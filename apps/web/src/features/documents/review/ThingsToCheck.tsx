"use client";

import type { components } from "@signora/contracts";

import { SmallText, TextButton } from "@/shared/ui";

import styles from "./review.module.css";

export type ReviewWarning = components["schemas"]["ReviewWarning"];

/**
 * What to look at before approving (Phase 6 §2, §7.1): the server's warnings for the saved fields,
 * each with its way forward. A field's warning shows the field; a party with no place to sign
 * gets "Add signature" (placing one for them) when the person can edit. Never a block; Approve
 * lists them again. With unsaved changes they describe what is saved, and say so.
 */
export function ThingsToCheck({
  warnings,
  stale,
  onShow,
  onAddSignature,
}: {
  warnings: readonly ReviewWarning[];
  stale: boolean;
  onShow: (fieldId: string) => void;
  onAddSignature: ((partyId: string) => void) | null;
}) {
  return (
    <>
      <ul className={styles.rows} aria-label="Things to check">
        {warnings.map((warning, index) => (
          <li key={`${warning.code}-${warning.field_id ?? warning.party_id ?? index}`} className={styles.line}>
            <span className={styles.name}>{warning.message}</span>
            {warning.field_id ? (
              <TextButton onClick={() => onShow(warning.field_id ?? "")}>Show me</TextButton>
            ) : warning.code === "party_cannot_sign" && warning.party_id && onAddSignature ? (
              <TextButton onClick={() => onAddSignature(warning.party_id ?? "")}>Add signature</TextButton>
            ) : null}
          </li>
        ))}
      </ul>
      {stale ? <SmallText>These are for the saved fields. Save to check your changes.</SmallText> : null}
    </>
  );
}
