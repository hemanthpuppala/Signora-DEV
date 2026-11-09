import type { ButtonHTMLAttributes, ReactNode } from "react";

import styles from "./items.module.css";

/**
 * A list of things, each with its actions (a document's versions, an envelope's recipients): one
 * hairline panel, a row each; a row's title and state on its first line (``ItemHead``), what it
 * is under it, and its actions on their own line under a rule (``ItemActions``), set apart from
 * what it says. ``ordered`` for a list whose order means something.
 */
export function ItemList({ label, ordered = false, children }: { label: string; ordered?: boolean; children: ReactNode }) {
  const List = ordered ? "ol" : "ul";
  return (
    <List className={styles.items} aria-label={label}>
      {children}
    </List>
  );
}

/** One row of an ``ItemList``; ``current`` marks the one on screen. */
export function Item({ current = false, children }: { current?: boolean; children: ReactNode }) {
  return <li className={current ? `${styles.item} ${styles.current}` : styles.item}>{children}</li>;
}

/** A row's title and its state, on one line. */
export function ItemHead({ children }: { children: ReactNode }) {
  return <div className={styles.head}>{children}</div>;
}

/** A row's actions: one line under a rule. ``end`` goes at the far end (an icon). */
export function ItemActions({ children, end }: { children: ReactNode; end?: ReactNode }) {
  return (
    <div className={styles.actions}>
      {children}
      {end ? <span className={styles.end}>{end}</span> : null}
    </div>
  );
}

/** A small word action in ``ItemActions``. */
export function ItemAction(props: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "type">) {
  return <button type="button" className={styles.action} {...props} />;
}
