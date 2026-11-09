"use client";

import styles from "./envelopes.module.css";

export type Shown = {
  /** Where: PDF points on the page as displayed. */
  places: readonly { page: number; rect: readonly number[]; option_value: string | null }[];
  holds: string;
  value: string;
  /** Given when signing (a signer's name): drawn quieter, as what is to come, not a value. */
  atSigning?: boolean;
};

/**
 * Values drawn in their boxes on one page (the send's review step, the envelope page): text in its
 * box, a tick for a ticked checkbox, a mark on the chosen option of a choice, and a signer's name
 * to come (given when they sign) in a quieter ink. Coordinates are PDF
 * points; ``scale`` only paints them. Visual only: the same values are listed in words beside it.
 */
export function ValuesOverlay({ page, scale, shown }: { page: number; scale: number; shown: readonly Shown[] }) {
  return (
    <div className={styles.values} aria-hidden="true">
      {shown.flatMap((item, i) =>
        item.places
          .filter((place) => place.page === page)
          .map((place, j) => {
            const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = place.rect;
            const height = (y1 - y0) * scale;
            let text: string | null = item.value;
            if (item.holds === "checkbox") text = item.value === "true" ? "✓" : null;
            if (item.holds === "choice") text = place.option_value === item.value ? "✓" : null;
            if (text === null) return null;
            return (
              <span
                key={`${i}-${j}`}
                className={item.atSigning ? `${styles.value} ${styles.atSigning}` : styles.value}
                style={{
                  left: x0 * scale,
                  top: y0 * scale,
                  width: (x1 - x0) * scale,
                  height,
                  fontSize: Math.max(8, Math.min(height * 0.72, 16 * scale)),
                }}
              >
                {text}
              </span>
            );
          }),
      )}
    </div>
  );
}
