import Link from "next/link";
import type { ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./display.module.css";

export function TablePanel({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx(styles.tablePanel, className)}>{children}</div>;
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
