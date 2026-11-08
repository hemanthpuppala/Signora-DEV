import { describe, expect, it } from "vitest";

import { looksLikeEmail } from "./email";

describe("looksLikeEmail", () => {
  it.each([
    ["rosa@example.com", true],
    ["rosa.hale+signora@firm.co.uk", true],
    ["ho@sakdf.cm", true], // well-formed (.cm is a real domain); only sending proves it exists
    ["  rosa@example.com  ", true],
    ["hiaf", false],
    ["rosa@", false],
    ["@example.com", false],
    ["rosa@localhost", false], // the server requires a dot in the domain
    ["ro sa@example.com", false],
    ["rosa@@example.com", false],
    ["", false],
  ])("%j -> %s", (value, expected) => {
    expect(looksLikeEmail(value)).toBe(expected);
  });
});
