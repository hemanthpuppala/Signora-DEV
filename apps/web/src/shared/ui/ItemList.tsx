import type { ButtonHTMLAttributes, ReactNode } from "react";

import styles from "./items.module.css";

/**
 * A list of things, each with its actions (a document's versions, an envelope's recipients): one
 * hairline panel, a row each; a row's title and state on its first line (``ItemHead``), what it
 * is under it, and its actions on their own line under a rule (``ItemActions``), set apart from
 * what it says. ``ordered`` for a list whose order means something.
 */
export function ItemList({
  label,
  ordered = false,
  cards = false,
  children,
}: {
  label: string;
  ordered?: boolean;
  /** Each row a card of its own, apart from the next (people, as document cards are). */
  cards?: boolean;
  children: ReactNode;
}) {
  const List = ordered ? "ol" : "ul";
  return (
    <List className={cards ? styles.cards : styles.items} aria-label={label}>
      {children}
    </List>
  );
}

/**
 * One row of an ``ItemList``; ``current`` marks the one on screen. ``leading`` sits at the start
 * of the row (a monogram, a page), ``actions`` (an ``ItemActions``) across its foot.
 */
export function Item({
  current = false,
  leading,
  actions,
  children,
}: {
  current?: boolean;
  leading?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const classes = [styles.item, current && styles.current, leading ? styles.withLeading : null].filter(Boolean).join(" ");
  return (
    <li className={classes}>
      {leading ? <div className={styles.leading}>{leading}</div> : null}
      {leading ? <div className={styles.body}>{children}</div> : children}
      {actions}
    </li>
  );
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
