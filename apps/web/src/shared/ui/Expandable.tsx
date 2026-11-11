"use client";

import { Children, isValidElement, useLayoutEffect, useRef, type CSSProperties, type ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./expandable.module.css";
import { Icon } from "./Icon";

const ROWS_BELOW = 2; // an open row shows with this many rows under it

/**
 * A list of rows that open in place (field review's fields; later, an envelope's recipients).
 * ``scrollable``: the list scrolls inside itself, at most the design system's table height while
 * every row is closed; when one opens it comes to the top and the list is exactly as tall as that
 * row and the two under it (Phase 6 §7.1). It measures itself when the open row (read from its
 * rows' ``expanded``) or the number of rows changes, not on every render: typing in the open row's
 * form re-renders the list, and the row's own size is watched.
 */
export function ExpandableList({
  label,
  children,
  scrollable = false,
}: {
  label: string;
  children: ReactNode;
  scrollable?: boolean;
}) {
  const ref = useRef<HTMLUListElement>(null);
  const shown = useRef<Element | null>(null);
  const items = Children.toArray(children);
  const openRow = items.find((row) => isValidElement<{ expanded?: boolean }>(row) && row.props.expanded);
  const openId = isValidElement(openRow) ? openRow.key : null;
  const rows = items.length;
  // Sizes the list to its open row and the rows under it, and brings that row to the top.
  useLayoutEffect(() => {
    const element = ref.current;
    if (!scrollable || !element) return undefined;
    const open = element.querySelector<HTMLElement>(`:scope > .${styles.open}`);
    const fit = () => {
      if (!open) {
        element.style.maxHeight = "";
        return;
      }
      let height = open.offsetHeight;
      let next = open.nextElementSibling as HTMLElement | null;
      for (let i = 0; i < ROWS_BELOW && next; i += 1) {
        height += next.offsetHeight;
        next = next.nextElementSibling as HTMLElement | null;
      }
      if (height > 0) element.style.maxHeight = `${height + 1}px`; // + the list's top hairline
    };
    fit();
    if (open && open !== shown.current) {
      const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
      if (typeof element.scrollTo === "function") element.scrollTo({ top: open.offsetTop, behavior: still ? "auto" : "smooth" });
      else element.scrollTop = open.offsetTop;
    }
    shown.current = open;
    // The open row's content changes size as it is edited (a choice's options, a new party form).
    if (!open || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(fit);
    observer.observe(open);
    return () => observer.disconnect();
  }, [scrollable, openId, rows]);
  return (
    <ul ref={ref} className={cx(styles.list, scrollable && styles.scrollable)} aria-label={label}>
      {children}
    </ul>
  );
}

/**
 * One row that opens in place, like a dropdown of its details (Phase 6 §7.1): a button with the
 * row's title and one line of facts, and, when open, its content as a labelled region under it.
 * The button is named by the title alone; the facts line is its description.
 * ``lead`` is a small mark before the title (a party's tone); ``depth`` indents a row under
 * another. Hairlines separate the rows; the open one is set off by its surface.
 */
export function ExpandableRow({
  id,
  title,
  meta,
  lead,
  expanded,
  onToggle,
  regionLabel,
  depth = 0,
  tone = "default",
  children,
}: {
  id: string;
  title: ReactNode;
  meta?: ReactNode;
  lead?: ReactNode;
  expanded: boolean;
  onToggle: () => void;
  /** The open content's accessible name, e.g. "Details of Company". */
  regionLabel: string;
  depth?: number;
  /** "add": the row that adds one (a plus instead of the chevron). */
  tone?: "default" | "add";
  children?: ReactNode;
}) {
  const panelId = `${id}-details`;
  const indent = { "--depth": depth } as CSSProperties;
  return (
    <li id={id} className={cx(styles.row, expanded && styles.open)} style={indent}>
      <button
        type="button"
        className={cx(styles.head, tone === "add" && styles.add)}
        aria-expanded={expanded}
        aria-controls={expanded ? panelId : undefined}
        aria-labelledby={`${id}-title`}
        aria-describedby={meta ? `${id}-meta` : undefined}
        onClick={onToggle}
      >
        {tone === "add" ? <Icon name="plus" className={styles.lead} /> : lead ? <span className={styles.lead}>{lead}</span> : null}
        <span className={styles.text}>
          <span id={`${id}-title`} className={styles.title}>
            {title}
          </span>
          {meta ? (
            <span id={`${id}-meta`} className={styles.meta}>
              {meta}
            </span>
          ) : null}
        </span>
        {tone === "add" ? null : <Icon name="chevron" className={styles.chevron} />}
      </button>
      {expanded ? (
        <div id={panelId} role="region" aria-label={regionLabel} className={styles.body}>
          {children}
        </div>
      ) : null}
    </li>
  );
}
