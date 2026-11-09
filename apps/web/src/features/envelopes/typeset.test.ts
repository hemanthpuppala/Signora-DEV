import { describe, expect, it } from "vitest";

import vectors from "../../../../../packages/contracts/vectors/date-formats.json";

import { written } from "./typeset";

const DATE_TYPES = new Set(["date", "date_signed", "date_of_birth", "day", "month", "year"]);

describe("a value written as its field says", () => {
  // The same examples the API's tests run (review.formats.written). A date type's format always
  // comes from the API with its default applied, so the cases without one are the API's alone.
  const cases = vectors.cases.filter((c) => c.format !== null || !DATE_TYPES.has(c.holds));
  it.each(cases)("$holds in $format: $value is $written", ({ holds, value, format, written: expected }) => {
    expect(written(holds, value, format)).toBe(expected);
  });
});
