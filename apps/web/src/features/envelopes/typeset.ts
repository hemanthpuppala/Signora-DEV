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
  align: "left" | "center";
};

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;

const two = (n: number) => String(n).padStart(2, "0");
function ordinal(day: number): string {
  const teen = day % 100 >= 11 && day % 100 <= 13;
  const suffix = teen ? "th" : (({ 1: "st", 2: "nd", 3: "rd" }) as Record<number, string>)[day % 10] ?? "th";
  return `${day}${suffix}`;
}

/**
 * A canonical value as its field writes it (the server's review.formats.written; the two are
 * tested against the same examples, packages/contracts/vectors/date-formats.json). ``format`` is
 * the field's as the API sends it, its type's default already applied; none: written as it is,
 * as is a value that is not canonical.
 */
export function written(holds: string, value: string, format: string | null): string {
  if (!format) return value;
  if (holds === "day") {
    const day = Number(value);
    return /^\d+$/.test(value) ? (format === "Dth" ? ordinal(day) : String(day)) : value;
  }
  if (holds === "month") {
    const number = /^\d+$/.test(value) ? Number(value) : MONTHS.findIndex((m) => m.toLowerCase() === value.toLowerCase()) + 1;
    if (number < 1 || number > 12) return value;
    return format === "Month" ? (MONTHS[number - 1] ?? value) : two(number);
  }
  if (holds === "year") return format === "YY" ? value.slice(-2) : value;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const name = MONTHS[month - 1];
  if (!name || day < 1 || day > 31) return value;
  switch (format) {
    case "MM/DD/YYYY":
      return `${two(month)}/${two(day)}/${year}`;
    case "DD/MM/YYYY":
      return `${two(day)}/${two(month)}/${year}`;
    case "MM/DD/YY":
      return `${two(month)}/${two(day)}/${two(year % 100)}`;
    case "DD/MM/YY":
      return `${two(day)}/${two(month)}/${two(year % 100)}`;
    case "YYYY-MM-DD":
      return value;
    case "D Month YYYY":
      return `${day} ${name} ${year}`;
    default:
      return `${name} ${day}, ${year}`;
  }
}

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
  const drawn = Math.max(fitted, floor);
  const width = perPoint * drawn;
  return {
    size: drawn,
    // Centred in its box (the server's rule); a value that had to shrink fills it from its left.
    x: rule.align === "center" ? x0 + Math.max(0, x1 - x0 - width) / 2 : x0,
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
  // ``text`` as its field writes it (``written``): the server measures the same.
  return places.every((place) => !typeset(text, place.rect, place.text_size, face, rule).squeeze);
}
