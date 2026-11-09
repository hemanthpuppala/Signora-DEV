"use client";

import styles from "./envelopes.module.css";
import { typeset, useFontReady, type FitRule, type Typeface } from "./typeset";

export type Shown = {
  /** Where: PDF points on the page as displayed; the agreement's text size beside it, if measured. */
  places: readonly { page: number; rect: readonly number[]; option_value: string | null; text_size: number | null }[];
  holds: string;
  value: string;
  /** Given when signing (a signer's name): drawn quieter, as what is to come, not a value. */
  atSigning?: boolean;
};

/**
 * Values drawn on one page as the signed PDF will draw them (the send's review step, the envelope
 * page): in the envelope's font, on the box's line, at the agreement's text size, smaller only when
 * the box is too narrow; a tick for a ticked checkbox or the chosen option; a signer's name to come
 * in a quieter ink. Coordinates are PDF points; ``scale`` only paints them. Visual only: the same
 * values are listed in words beside it.
 */
export function ValuesOverlay({
  page,
  scale,
  shown,
  font,
  fit,
}: {
  page: number;
  scale: number;
  shown: readonly Shown[];
  font: Typeface;
  fit: FitRule;
}) {
  const ready = useFontReady(font);
  return (
    <svg className={styles.values} aria-hidden="true" data-font-ready={ready || undefined}>
      {shown.flatMap((item, i) =>
        item.places
          .filter((place) => place.page === page)
          .map((place, j) => {
            const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = place.rect;
            const mark = item.holds === "checkbox" || item.holds === "choice";
            if (mark) {
              const ticked = item.holds === "checkbox" ? item.value === "true" : place.option_value === item.value;
              if (!ticked) return null;
              const height = y1 - y0;
              return (
                <text
                  key={`${i}-${j}`}
                  className={styles.value}
                  x={((x0 + x1) / 2) * scale}
                  y={(y1 - height * 0.15) * scale}
                  fontSize={height * 0.9 * scale}
                  textAnchor="middle"
                >
                  ✓
                </text>
              );
            }
            const set = typeset(item.value, place.rect, place.text_size, font, fit);
            return (
              <text
                key={`${i}-${j}`}
                className={item.atSigning ? `${styles.value} ${styles.atSigning}` : styles.value}
                x={x0 * scale}
                y={set.baseline * scale}
                fontSize={set.size * scale}
                fontFamily={`"${font.family}", var(--sans)`}
                {...(set.squeeze ? { textLength: set.squeeze * scale, lengthAdjust: "spacingAndGlyphs" } : {})}
              >
                {item.value}
              </text>
            );
          }),
      )}
    </svg>
  );
}
