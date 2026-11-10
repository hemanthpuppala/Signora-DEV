import type { ReactNode } from "react";

import styles from "./actionBar.module.css";

/**
 * A screen's actions on one line that stays in view under the top bar (Phase 6 §7.1), with what
 * is changing now beside them ("1 unsaved change"); what is simply true (the version, its state)
 * belongs under the title (``MetaLine``). Beside a document it heads the details column
 * (``DetailsPane``), so the document keeps the window's full height. One per screen.
 */
export function ActionBar({ label, children, actions }: { label: string; children?: ReactNode; actions?: ReactNode }) {
  if (!children && !actions) return null; // nothing to do and nothing changing: no bar
  return (
    <div className={styles.bar} role="region" aria-label={label}>
      {children ? <div className={styles.status}>{children}</div> : null}
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </div>
  );
}
