import type { ReactNode } from "react";

import styles from "./rowActions.module.css";

/**
 * Text actions for one table row ("Resend", "Revoke"), spaced so tracked uppercase labels read as
 * separate actions, and aligned to the row's end.
 */
export function RowActions({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.actions} role="group" aria-label={label}>
      {children}
    </div>
  );
}
