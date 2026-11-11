import type { ReactNode } from "react";

import styles from "./actionBar.module.css";

/**
 * A screen's state and its actions on one line that stays in view under the top bar (Phase 6
 * §7.1): what is true now on the left ("Version 2 · Needs approval · 1 thing to check"), what can
 * be done on the right (Approve; with unsaved changes Undo, Discard, Save). One per screen.
 */
export function ActionBar({ label, children, actions }: { label: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className={styles.bar} role="region" aria-label={label}>
      <div className={styles.status}>{children}</div>
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </div>
  );
}
