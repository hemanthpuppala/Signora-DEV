import type { ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./chip.module.css";

/** A row of chips that choose one thing (a filter, a field's place). */
export function ChipGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.group} role="group" aria-label={label}>
      {children}
    </div>
  );
}

/**
 * One choice in a ChipGroup (Phase 6 §7.1): a small square choice, filled when chosen, so what is chosen
 * reads at a glance; ``aria-pressed`` says the same to assistive technology.
 */
export function Chip({
  selected,
  onClick,
  children,
  label,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
  /** The accessible name when the words alone are not enough ("Place 2, page 1"). */
  label?: string;
}) {
  return (
    <button type="button" aria-pressed={selected} aria-label={label} className={cx(styles.chip, selected && styles.on)} onClick={onClick}>
      {children}
    </button>
  );
}
