import Link from "next/link";
import type { ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./display.module.css";

/**
 * A table inside a hairline panel. Long tables scroll inside the panel (the header row stays
 * visible) instead of growing the page; the panel is focusable so keyboard users can scroll it.
 */
export function TablePanel({
  children,
  label,
  className,
}: {
  children: ReactNode;
  /** What the table lists ("Members"); announced when the panel is focused. */
  label: string;
  className?: string;
}) {
  return (
    <div className={cx(styles.tablePanel, className)} role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

/**
 * A table cell holding one row action ("Resend"). It is only as wide as its content, so the data
 * columns share the table's width and each action gets a column of its own at the row's end.
 * ``grow`` lets one action column take the free space and centre its button in it.
 */
export function ActionCell({ children, grow = false }: { children: ReactNode; grow?: boolean }) {
  return <td className={cx(styles.actionCell, grow && styles.actionCellGrow)}>{children}</td>;
}

/** The header of an ``ActionCell`` column (no visible title; named for screen readers). */
export function ActionHeader({ label, grow = false }: { label: string; grow?: boolean }) {
  return (
    <th className={cx(styles.actionCell, grow && styles.actionCellGrow)} aria-label={label}>
      <span className={styles.visuallyHidden}>{label}</span>
    </th>
  );
}

export const STATUSES = [
  "draft",
  "pending",
  "sent",
  "opened",
  "viewed",
  "signed",
  "completed",
  "declined",
  "expired",
  "cancelled",
] as const;

export type Status = (typeof STATUSES)[number];

const DEFAULT_LABELS: Record<Status, string> = {
  draft: "Draft",
  pending: "Pending",
  sent: "Sent",
  opened: "Opened",
  viewed: "Viewed",
  signed: "Signed",
  completed: "Completed",
  declined: "Declined",
  expired: "Expired",
  cancelled: "Cancelled",
};

/** Status pill: the dot carries the color (the only color in the product); the label stays white. */
export function StatusPill({ status, label }: { status: Status; label?: string }) {
  return (
    <span className={cx(styles.status, styles[`st-${status}`])}>
      <i
        className={cx(
          styles.dot,
          status === "expired" && styles.dotDashed,
          status === "cancelled" && styles.dotRing,
        )}
        aria-hidden="true"
      />
      {label ?? DEFAULT_LABELS[status]}
    </span>
  );
}

export type NoticeProps = {
  tone?: "info" | "warning";
  title?: string;
  children: ReactNode;
  action?: ReactNode;
};

export function Notice({ tone = "info", title, children, action }: NoticeProps) {
  return (
    <div
      className={cx(styles.notice, tone === "warning" && styles.noticeWarning)}
      role={tone === "warning" ? "alert" : "note"}
    >
      <div className={styles.noticeBody}>
        {title ? <span className={styles.noticeTitle}>{title}</span> : null}
        <span>{children}</span>
      </div>
      {action}
    </div>
  );
}

export function MetricTile({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricValue}>{value}</span>
      <span className={styles.metricLabel}>{label}</span>
    </div>
  );
}

export function MetricGrid({ children }: { children: ReactNode }) {
  return <div className={styles.metricGrid}>{children}</div>;
}

export type TabItem = { href: string; label: string; active?: boolean };

export function Tabs({ items, label }: { items: readonly TabItem[]; label: string }) {
  return (
    <nav className={styles.tabs} aria-label={label}>
      {items.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className={cx(styles.tab, item.active && styles.tabActive)}
          aria-current={item.active ? "page" : undefined}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
