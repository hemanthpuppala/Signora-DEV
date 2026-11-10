import { describe, expect, it } from "vitest";

import { askedFields } from "./conditions";

const A = { id: "a", depends_on: { field_id: "b", option: "checked" } };
const B = { id: "b", depends_on: { field_id: "c", option: "Gold" } };
const C = { id: "c", depends_on: null };

describe("which fields are asked", () => {
  it.each([[[A, B, C]], [[C, B, A]], [[B, A, C]]])("follows a chain of conditions whatever order the fields come in", (fields) => {
    // B is hidden once C is no longer Gold: the tick left in it does not keep A.
    expect([...askedFields(fields, { a: "left over", b: "true", c: "Silver" })]).toEqual(["c"]);
    expect([...askedFields(fields, { b: "true" })]).toEqual(["c"]);
    expect([...askedFields(fields, { b: "true", c: "Gold" })].sort()).toEqual(["a", "b", "c"]);
    expect([...askedFields(fields, { c: "Gold" })].sort()).toEqual(["b", "c"]);
  });

  it("asks nothing of a field whose condition's field is not in the form, or of a loop", () => {
    const orphan = { id: "o", depends_on: { field_id: "gone", option: "checked" } };
    const x = { id: "x", depends_on: { field_id: "y", option: "checked" } };
    const y = { id: "y", depends_on: { field_id: "x", option: "checked" } };
    expect([...askedFields([orphan, x, y, C], { gone: "true", x: "true", y: "true" })]).toEqual(["c"]);
  });
});
