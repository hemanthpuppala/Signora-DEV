import type { ReactNode } from "react";

import styles from "./layout.module.css";

/**
 * A list's controls on one line above it: the search, taking the room, then what orders or filters
 * the list at its end. On a phone they stack, the search first.
 */
export function ListControls({ search, children }: { search: ReactNode; children?: ReactNode }) {
  return (
    <div className={styles.listControls}>
      <div className={styles.listSearch}>{search}</div>
      {children ? <div className={styles.listTools}>{children}</div> : null}
    </div>
  );
}
