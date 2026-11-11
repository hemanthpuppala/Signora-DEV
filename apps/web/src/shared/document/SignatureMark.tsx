"use client";

import { PAD_HEIGHT, PAD_WIDTH, type Stroke } from "@/shared/ui";

import { useFontReady, type Typeface } from "./typeset";

export type Mark =
  | { method: "drawn"; strokes: readonly Stroke[] }
  | { method: "typed"; text: string; font: Typeface };

/**
 * A signature or initials drawn in its box as the signed PDF draws it (Phase 8 §5.3): scaled to the
 * box's height, its shape kept, centred. A drawing is its own strokes; a typed one its text in its
 * handwriting font.
 */
export function SignatureMark({ mark, width, height }: { mark: Mark; width: number; height: number }) {
  const ready = useFontReady(mark.method === "typed" ? mark.font : null);
  if (mark.method === "typed") {
    return (
      <svg width={width} height={height} aria-hidden="true" data-font-ready={ready || undefined}>
        <text
          x={width / 2}
          y={height * 0.72}
          textAnchor="middle"
          fontFamily={`"${mark.font.family}", cursive`}
          fontSize={height * 0.7}
          fill="var(--paper-ink)"
        >
          {mark.text}
        </text>
      </svg>
    );
  }
  const scale = Math.min(width / PAD_WIDTH, height / PAD_HEIGHT);
  const dx = (width - PAD_WIDTH * scale) / 2;
  const dy = (height - PAD_HEIGHT * scale) / 2;
  return (
    <svg width={width} height={height} aria-hidden="true">
      <g transform={`translate(${dx} ${dy}) scale(${scale})`} fill="none" stroke="var(--paper-ink)" strokeWidth={6} strokeLinecap="round" strokeLinejoin="round">
        {mark.strokes.map((stroke, index) => (
          <polyline key={index} points={stroke.map(([x, y]) => `${x},${y}`).join(" ")} />
        ))}
      </g>
    </svg>
  );
}
