"use client";

import type { components } from "@signora/contracts";

import { SmallText, TextButton } from "@/shared/ui";

import styles from "./review.module.css";

export type ReviewWarning = components["schemas"]["ReviewWarning"];

/**
 * What to look at before approving (Phase 6 §2): the server's warnings for the saved fields, each
 * with "Show me" when it is about one field. Never a block; Approve lists them again. With unsaved
 * changes they describe what is saved, and say so.
 */
export function ThingsToCheck({
  warnings,
  stale,
  onShow,
}: {
  warnings: readonly ReviewWarning[];
  stale: boolean;
  onShow: (fieldId: string) => void;
}) {
  if (warnings.length === 0) return null;
  return (
    <section className={styles.check} aria-label="Things to check">
      <h3 className={styles.checkTitle}>Things to check</h3>
      <ul className={styles.checkList}>
        {warnings.map((warning, index) => (
          <li key={`${warning.code}-${warning.field_id ?? warning.party_id ?? index}`}>
            <span>{warning.message}</span>
            {warning.field_id ? (
              <TextButton onClick={() => onShow(warning.field_id ?? "")}>Show me</TextButton>
            ) : null}
          </li>
        ))}
      </ul>
      {stale ? <SmallText>These are for the saved fields. Save to check your changes.</SmallText> : null}
    </section>
  );
}
