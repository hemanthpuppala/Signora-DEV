"use client";

import { useSyncExternalStore } from "react";

/** The font values are drawn in and the server's fit rule (typesetting), as the API sends them. */
export type Typeface = { family: string; url: string };
export type FitRule = {
  min_size: number;
  fallback_ratio: number;
  fallback_cap: number;
  baseline_ratio: number;
  baseline_min: number;
};

// The font is loaded once per page view (FontFace: governed by font-src, no stylesheet needed).
const loaded = new Set<string>(); // asked for
const readyFamilies = new Set<string>(); // in document.fonts
const listeners = new Set<() => void>();
function loadFont(face: Typeface): void {
  if (loaded.has(face.family) || typeof FontFace === "undefined") return;
  loaded.add(face.family);
  const font = new FontFace(face.family, `url(${face.url})`);
  void font.load().then(
    (ready) => {
      document.fonts.add(ready);
      readyFamilies.add(face.family);
      listeners.forEach((notify) => notify());
    },
    () => loaded.delete(face.family), // not loaded: the next overlay tries again
  );
}
export function useFontReady(face: Typeface): boolean {
  return useSyncExternalStore(
    (notify) => {
      listeners.add(notify);
      loadFont(face);
      return () => listeners.delete(notify);
    },
    () => readyFamilies.has(face.family),
    () => false,
  );
}

let canvas: HTMLCanvasElement | null = null;
/** A text's width at 1 pt in the font (the browser's measure of the same file the PDF embeds). */
function widthPerPoint(text: string, family: string): number {
  canvas ??= document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) return 0;
  context.font = `100px "${family}"`;
  return context.measureText(text).width / 100;
}

/** The server's rule (typesetting.fit), with its numbers: the size and baseline of a value in a box. */
export function typeset(text: string, rect: readonly number[], textSize: number | null, face: Typeface, rule: FitRule) {
  const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = rect;
  const size = textSize ?? Math.min(rule.fallback_cap, (y1 - y0) * rule.fallback_ratio);
  const perPoint = widthPerPoint(text, face.family);
  const fitted = perPoint > 0 ? Math.min(size, (x1 - x0) / perPoint) : size;
  const floor = Math.min(size, rule.min_size);
  return {
    size: Math.max(fitted, floor),
    // Wider than the box even at the floor (a recipient's long email): squeezed into the box.
    squeeze: fitted < floor ? x1 - x0 : undefined,
    baseline: y1 - Math.max(rule.baseline_min, Math.max(fitted, floor) * rule.baseline_ratio),
  };
}

/** Whether a value can be drawn in every place of its field (the server checks the same on Send). */
export function fitsEverywhere(
  text: string,
  places: readonly { rect: readonly number[]; text_size: number | null }[],
  face: Typeface,
  rule: FitRule,
): boolean {
  return places.every((place) => !typeset(text, place.rect, place.text_size, face, rule).squeeze);
}
