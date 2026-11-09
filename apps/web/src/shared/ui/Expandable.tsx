"use client";

import type { CSSProperties, ReactNode, Ref } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./expandable.module.css";
import { Icon } from "./Icon";

/** A list of rows that open in place (field review's fields; later, an envelope's recipients). */
export function ExpandableList({
  label,
  children,
  listRef,
}: {
  label: string;
  children: ReactNode;
  listRef?: Ref<HTMLUListElement> | undefined;
}) {
  return (
    <ul ref={listRef} className={styles.list} aria-label={label}>
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
