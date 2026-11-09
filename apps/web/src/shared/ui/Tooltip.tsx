"use client";

import { useState, type ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import { Icon, type IconName } from "./Icon";
import styles from "./tooltip.module.css";

/**
 * A short label shown above what it wraps, on hover and on keyboard focus; Escape hides it
 * (WCAG 1.4.13). It is visual only: what it wraps must carry the same words for assistive
 * technology (an icon button's name, or the text itself).
 */
export function Tooltip({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string | undefined;
}) {
  const [dismissed, setDismissed] = useState(false);
  return (
    <span
      className={cx(styles.anchor, className)}
      onKeyDown={(event) => {
        if (event.key === "Escape") setDismissed(true);
      }}
      onMouseLeave={() => setDismissed(false)}
      onBlur={() => setDismissed(false)}
    >
      {children}
      <span className={cx(styles.tip, dismissed && styles.dismissed)} aria-hidden="true">
        {label}
      </span>
    </span>
  );
}

type IconButtonBase = { label: string; icon: IconName; filled?: boolean };
export type IconButtonProps = IconButtonBase &
  ({ href: string; download?: boolean; onClick?: never; disabled?: never } | { href?: never; download?: never; onClick: () => void; disabled?: boolean });

/**
 * A square button (or link) that is only an icon: named by its label, which its tooltip shows.
 */
export function IconButton({ label, icon, filled, ...action }: IconButtonProps) {
  return (
    <Tooltip label={label}>
      {action.href !== undefined ? (
        <a className={styles.iconButton} href={action.href} download={action.download} aria-label={label}>
          <Icon name={icon} filled={filled} />
        </a>
      ) : (
        <button type="button" className={styles.iconButton} onClick={action.onClick} disabled={action.disabled} aria-label={label}>
          <Icon name={icon} filled={filled} />
        </button>
      )}
    </Tooltip>
  );
}
