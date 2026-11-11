"use client";

import styles from "./envelopes.module.css";
import { typeset, useFontReady, written, writtenIn, type FitRule, type Typeface } from "./typeset";

export type Shown = {
  /** Where: PDF points on the page as displayed; the agreement's text size beside it, if measured. */
  places: readonly { page: number; rect: readonly number[]; option_value: string | null; text_size: number | null }[];
  holds: string;
  value: string;
  /** How a date or a part of one is written (the field's format; none for other types). */
  format?: string | null;
  /** Given when signing (a signer's name): drawn quieter, as what is to come, not a value. */
  atSigning?: boolean;
};

/**
 * Values drawn on one page as the signed PDF will draw them (the send's review step, the envelope
 * page): in the envelope's font, on the box's line, at the agreement's text size, smaller only when
 * the box is too narrow; a tick for a ticked checkbox or the chosen option, and the chosen option's
 * words in a dropdown's box; a signer's name to come
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
      {shown.flatMap((item, i) => {
        const asText = writtenIn(item.holds, item.places);
        return item.places
          .filter((place) => place.page === page)
          .map((place, j) => {
            const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = place.rect;
            // A tick, unless the value is written here: a dropdown's box shows the chosen option.
            if (!asText.includes(place)) {
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
            const text = written(item.holds, item.value, item.format ?? null);
            const set = typeset(text, place.rect, place.text_size, font, fit);
            return (
              <text
                key={`${i}-${j}`}
                className={item.atSigning ? `${styles.value} ${styles.atSigning}` : styles.value}
                x={set.x * scale}
                y={set.baseline * scale}
                fontSize={set.size * scale}
                fontFamily={`"${font.family}", var(--sans)`}
                {...(set.squeeze ? { textLength: set.squeeze * scale, lengthAdjust: "spacingAndGlyphs" } : {})}
              >
                {text}
              </text>
            );
          });
      })}
    </svg>
  );
}
