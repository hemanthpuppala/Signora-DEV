"use client";

import { useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

import styles from "./items.module.css";

const PEEK = 28; // pixels of the next row that show under the last one shown

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
  visible,
  children,
}: {
  label: string;
  ordered?: boolean;
  /** Each row a card of its own, apart from the next (people, as document cards are). */
  cards?: boolean;
  /** Show this many rows, the next one's edge peeking, and scroll the rest inside the list. */
  visible?: number;
  children: ReactNode;
}) {
  const List = ordered ? "ol" : "ul";
  const ref = useRef<HTMLOListElement & HTMLUListElement>(null);
  const [height, setHeight] = useState<number | undefined>(undefined);
  // Measured from the rows themselves (their heights vary): up to the row after the last shown,
  // with a little of it showing, so it reads as more to scroll to.
  useLayoutEffect(() => {
    const list = ref.current;
    if (!list || visible === undefined) return undefined;
    const measure = () => {
      const next = list.children[visible] as HTMLElement | undefined;
      // From the boxes on screen, not offsetTop: that counts from the nearest positioned ancestor,
      // which the list and its rows need not share. Scrolled lists count back what they scrolled.
      setHeight(
        next ? next.getBoundingClientRect().top - list.getBoundingClientRect().top + list.scrollTop + PEEK : undefined,
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const watch = new ResizeObserver(measure);
    Array.from(list.children).forEach((row) => watch.observe(row));
    return () => watch.disconnect();
  }, [visible, children]);
  const className = [cards ? styles.cards : styles.items, height !== undefined ? styles.scrolls : null].filter(Boolean).join(" ");
  return (
    <List ref={ref} className={className} aria-label={label} style={height !== undefined ? { maxHeight: height } : undefined}>
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
