import { describe, expect, it, vi } from "vitest";

import vectors from "../../../../../packages/contracts/vectors/date-formats.json";
import numbers from "../../../../../packages/contracts/vectors/numbers.json";

import { fitsEverywhere, kept, MEASURED_AT, number, written } from "./typeset";

const DATE_TYPES = new Set(["date", "date_signed", "date_of_birth", "day", "month", "year"]);

describe("a value written as its field says", () => {
  // The same examples the API's tests run (review.formats.written). A date type's format always
  // comes from the API with its default applied, so the cases without one are the API's alone.
  const cases = vectors.cases.filter((c) => c.format !== null || !DATE_TYPES.has(c.holds));
  it.each(cases)("$holds in $format: $value is $written", ({ holds, value, format, written: expected }) => {
    expect(written(holds, value, format)).toBe(expected);
  });
});

describe("a typed value as the server keeps it", () => {
  it("reads a two-digit year in today's century, and leaves everything else as typed", () => {
    const century = Math.floor(new Date().getUTCFullYear() / 100) * 100;
    expect(kept("year", "26")).toBe(String(century + 26));
    expect(kept("year", "2031")).toBe("2031");
    expect(kept("day", "26")).toBe("26");
    expect(kept("text", "26")).toBe("26");
  });
});

describe("a value's width", () => {
  it("is the sum of its characters' widths, as the server sums them: kerning never narrows it", () => {
    // A browser that kerns "AV": the pair measures narrower than its two letters.
    const measured: string[] = [];
    const canvas = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      font: "",
      measureText: (text: string) => {
        measured.push(text);
        return { width: (text === "AV" ? 1.2 : text.length * 0.7) * MEASURED_AT };
      },
    } as unknown as CanvasRenderingContext2D);
    const face = { family: "Kerned Test", url: "/font" };
    const rule = { min_size: 6, fallback_ratio: 0.72, fallback_cap: 11, baseline_ratio: 0.18, baseline_min: 1.5, align: "center" as const };
    // "AV" is 1.4 pt wide per point: at the 6 pt floor it needs 8.4 pt, so an 8 pt box is too narrow
    // (kerned, it would have measured 7.2 pt and passed).
    expect(fitsEverywhere("AV", [{ rect: [0, 0, 8, 12], text_size: 10 }], face, rule)).toBe(false);
    expect(fitsEverywhere("AV", [{ rect: [0, 0, 9, 12], text_size: 10 }], face, rule)).toBe(true);
    expect(measured).toEqual(["A", "V"]); // each character once, however often it is asked
    canvas.mockRestore();
  });
});

describe("a typed number is kept as the server keeps it (the server runs the same examples)", () => {
  it.each(numbers.kept)("$holds $typed is kept as $kept", ({ holds, typed, kept: canonical }) => {
    expect(number(holds, typed)).toEqual({ kept: canonical });
    expect(kept(holds, typed)).toBe(canonical); // what the preview draws and measures
  });

  it.each(numbers.refused)("$holds $typed is refused: $message", ({ holds, typed, message }) => {
    expect(number(holds, typed)).toEqual({ refused: message });
    expect(kept(holds, typed)).toBe(typed); // drawn as typed; the box says why
  });
});
