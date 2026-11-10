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

/** The months by name, in order: the one list for the month picker and a written date. */
export const MONTHS = [
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

export const NUMBER_MAX_DIGITS = 28;
const NUMBERS = new Set(["number", "currency", "percent"]);
// A sign, digits (commas between them are grouping), a decimal point: the digits 0-9 only.
const NUMBER = /^([+-]?)([0-9][0-9,]*)?(?:\.([0-9]*))?$/;

/**
 * A typed number, amount or percentage as the server keeps it, or why the server refuses it, in
 * its words (review.formats.check_value; the two run the same examples,
 * packages/contracts/vectors/numbers.json). Kept without grouping or leading zeros, with a decimal
 * part only when it says something. O(len(typed)).
 */
export function number(holds: string, typed: string): { kept: string } | { refused: string } {
  const text = holds === "percent" ? typed.trim().replace(/%$/, "").trimEnd() : typed.trim();
  const match = NUMBER.exec(text);
  const digits = (match?.[2] ?? "").replaceAll(",", "");
  const decimals = match?.[3] ?? "";
  if (!match || digits + decimals === "") return { refused: "Enter a number" };
  if ((digits + decimals).length > NUMBER_MAX_DIGITS) return { refused: `Use ${NUMBER_MAX_DIGITS} or fewer digits` };
  const whole = digits.replace(/^0+/, "") || "0";
  const part = /[1-9]/.test(decimals) ? decimals : "";
  const negative = match[1] === "-" && !(whole === "0" && part === "");
  const over = whole.length > 3 || (whole.length === 3 && whole > "100") || (whole === "100" && part !== "");
  if (holds === "percent" && (negative || over)) return { refused: "Enter a percentage from 0 to 100" };
  return { kept: `${negative ? "-" : ""}${whole}${part ? `.${part}` : ""}` };
}

/**
 * A typed value as the server keeps it (review.formats.check_value), where that changes what is
 * drawn: a year typed in two digits is kept whole, in today's century; a number is kept canonical
 * (``number``). Everything else, and a value the server would refuse, is drawn as typed.
 */
export function kept(holds: string, value: string): string {
  if (NUMBERS.has(holds)) {
    const judged = number(holds, value);
    return "kept" in judged ? judged.kept : value;
  }
  if (holds !== "year" || !/^\d{2}$/.test(value)) return value;
  return String(Math.floor(new Date().getUTCFullYear() / 100) * 100 + Number(value));
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
      advances.delete(face.family); // widths measured before it arrived were another font's
      listeners.forEach((notify) => notify());
    },
    () => loaded.delete(face.family), // not loaded: the next overlay tries again
  );
}
/**
 * Asks for the font and says once it is in: until then nothing measured or drawn is in it, so a
 * width is not to be judged. No font yet (the form still loading): not ready.
 */
export function useFontReady(face: Typeface | null | undefined): boolean {
  const family = face?.family;
  return useSyncExternalStore(
    (notify) => {
      listeners.add(notify);
      if (face) loadFont(face);
      return () => listeners.delete(notify);
    },
    () => family !== undefined && readyFamilies.has(family),
    () => false,
  );
}

/**
 * The size widths are measured at. A browser rounds a character's width to its pixel grid, so at
 * a small size each character is a little off and a long value is off by their sum. At the font's
 * own grid (2048 units to the em in a TrueType font such as the default) a character's width is
 * the font's number exactly, as the server reads it; in another grid the error is under 1/2048 of
 * the size per character.
 */
export const MEASURED_AT = 2048;

let canvas: HTMLCanvasElement | null = null;
const advances = new Map<string, Map<string, number>>(); // per family: a character's width at 1 pt
/**
 * A text's width at 1 pt in the font: the sum of its characters' own widths, as the server sums
 * them (typesetting.fit) and the PDF draws them. Measured a character at a time, so the browser's
 * kerning and ligatures, which the PDF does not have, never narrow it. O(len(text)).
 */
function widthPerPoint(text: string, family: string): number {
  canvas ??= document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) return 0;
  context.font = `${MEASURED_AT}px "${family}"`;
  let known = advances.get(family);
  if (!known) advances.set(family, (known = new Map()));
  let width = 0;
  for (const character of text) {
    let advance = known.get(character);
    if (advance === undefined) {
      advance = context.measureText(character).width / MEASURED_AT;
      known.set(character, advance);
    }
    width += advance;
  }
  return width;
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
