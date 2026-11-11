import { describe, expect, it } from "vitest";

import type { SignerField } from "./api";
import { allValues, guided, guideStep, pointerLabel, remaining } from "./guide";

const field = (id: string, extra: Partial<SignerField> = {}): SignerField => ({
  id,
  label: id,
  holds: "text",
  holds_label: null,
  format: null,
  party_id: "p-client",
  mine: true,
  required: true,
  options: [],
  depends_on: null,
  places: [{ page: 1, rect: [100, 100, 200, 120], option_value: null, text_size: 10 }],
  value: null,
  locked: false,
  draft: null,
  hidden: null,
  ...extra,
});

const at = (page: number, x: number, y: number) => [{ page, rect: [x, y, x + 50, y + 20], option_value: null, text_size: 10 }];

describe("the guide", () => {
  it("goes through the person's required fields in reading order: page, then top, then left", () => {
    const fields = [
      field("page2", { places: at(2, 10, 10) }),
      field("lower", { places: at(1, 10, 500) }),
      field("right", { places: at(1, 300, 100) }),
      field("left", { places: at(1, 10, 100) }),
      field("optional", { required: false, places: at(1, 0, 0) }),
      field("theirs", { mine: false, required: false, places: at(1, 0, 0) }),
      field("date", { holds: "date_signed", places: at(1, 0, 0) }),
    ];

    expect(guided(fields, {}).map((f) => f.id)).toEqual(["left", "right", "lower", "page2"]);
  });

  it("counts only what is still empty, and skips what was given before sending", () => {
    const fields = [field("a"), field("b"), field("c", { locked: true, value: "Maya Chen" })];

    expect(remaining(fields, { a: "Founder" }).map((f) => f.id)).toEqual(["b"]);
  });

  it("leaves out a field whose condition is not met, and asks it once it is", () => {
    const box = field("box", { holds: "checkbox", required: false });
    const topics = field("topics", { depends_on: { field_id: "box", option: "checked" } });

    expect(guided([box, topics], {}).map((f) => f.id)).toEqual([]);
    expect(guided([box, topics], { box: "true" }).map((f) => f.id)).toEqual(["topics"]);
  });

  it("reads every value the conditions need: shown ones and the person's drafts", () => {
    const fields = [field("mine"), field("sender", { mine: false, value: "Delaware" }), field("hidden", { mine: false, hidden: "private" })];

    expect(allValues(fields, { mine: "x" })).toEqual({ mine: "x", sender: "Delaware" });
  });

  it("says Start, then Next while fields are left, then Complete", () => {
    expect(guideStep(false, 3)).toBe("start");
    expect(guideStep(true, 2)).toBe("next");
    expect(guideStep(true, 0)).toBe("complete");
    expect(guideStep(false, 0)).toBe("complete");
  });

  it("words the pointer by what the field asks", () => {
    expect(pointerLabel(field("s", { holds: "signature", label: "Client signature" }))).toBe("Sign here");
    expect(pointerLabel(field("i", { holds: "initials" }))).toBe("Initial here");
    expect(pointerLabel(field("t", { label: "Full name" }))).toBe("Fill Full name");
    // Once a signature is adopted, one click signs: the pointer says so.
    expect(pointerLabel(field("s", { holds: "signature" }), true)).toBe("Click to sign");
    expect(pointerLabel(field("i", { holds: "initials" }), true, true)).toBe("Tap to initial");
  });
});
