import { describe, expect, it } from "vitest";

import { HOLD_GROUPS, HOLDS, type VersionFields } from "../fields";
import {
  addParty,
  addPlace,
  apply,
  begin,
  boxAt,
  clampRect,
  deleteField,
  deletePlace,
  fromView,
  moveParty,
  newField,
  nextOptionName,
  nudge,
  onEveryPage,
  redo,
  conditionKey,
  conditionOf,
  joinsOnSave,
  mayHold,
  removeParty,
  setOptionText,
  setRect,
  splitPlace,
  toFieldSet,
  undo,
  unsaved,
  updateField,
  updateParty,
  type Draft,
  type DraftField,
} from "./editor";

const A4 = { width: 595, height: 842 };
const PAGES = [A4, A4, A4];

const place = (id: string, page = 1, extra: Record<string, unknown> = {}) => ({
  id,
  page,
  rect: [100, 100, 200, 120] as [number, number, number, number],
  kind: "text",
  option_value: null,
  option_text: null,
  ...extra,
});

const VIEW = {
  status: "ready",
  revision: 4,
  roles: [
    { id: "firm", slug: "firm", label: "Firm", kind: "countersigner", kind_label: null, position: 3, field_count: 0 },
    { id: "client", slug: "client", label: "Client", kind: "signer", kind_label: null, position: 1, field_count: 2 },
    { id: "guarantor", slug: "guarantor", label: "Guarantor", kind: "signer", kind_label: "Guarantor", position: 2, field_count: 0 },
  ],
  fields: [
    {
      id: "plan",
      key: "client.plan",
      label: "Plan",
      holds: "choice",
      holds_label: null,
      filled_by: "role",
      role: "client",
      party_id: "client",
      origin: "detected",
      required: true,
      sensitive: false,
      depends_on: null,
      needs_review: null,
      placements: [
        place("gold", 1, { kind: "radio", option_value: "Gold", option_text: "Gold plan" }),
        place("silver", 1, { kind: "radio", option_value: "Silver", option_text: "Silver plan" }),
      ],
    },
    {
      id: "card",
      key: "client.card",
      label: "Card",
      holds: "text",
      holds_label: null,
      filled_by: "role",
      role: "client",
      party_id: "client",
      origin: "detected",
      required: true,
      sensitive: false,
      depends_on: { key: "client.plan", option: "Gold" },
      needs_review: "not sure who fills it",
      placements: [place("card-1"), place("card-2", 2)],
    },
  ],
} as unknown as VersionFields;

describe("the review editor", () => {
  it("turns the fields view into a draft by ids and back into the save body", () => {
    const draft = fromView(VIEW);

    expect(draft.parties.map((p) => p.id)).toEqual(["client", "guarantor", "firm"]); // signing order
    expect(draft.fields[1]?.depends_on).toEqual({ field_id: "plan", option: "Gold" }); // by id, not key
    const body = toFieldSet(draft, VIEW.revision);
    expect(body.revision).toBe(4);
    expect(body.parties[1]).toEqual({ id: "guarantor", label: "Guarantor", kind: "signer", kind_label: "Guarantor" });
    expect(body.fields[1]).toMatchObject({ id: "card", party_id: "client", depends_on: { field_id: "plan", option: "Gold" } });
    expect(body.fields[0]?.places.map((p) => [p.id, p.kind, p.option_value])).toEqual([
      ["gold", "radio", "Gold"],
      ["silver", "radio", "Silver"],
    ]);
  });

  it("clears a flag when its field changes, and conditions on a field that can no longer be one", () => {
    let draft = fromView(VIEW);
    draft = updateField(draft, "card", { required: false });
    expect(draft.fields[1]?.needs_review).toBeNull();

    draft = updateField(draft, "plan", { holds: "text" });
    expect(draft.fields[1]?.depends_on).toBeNull();
    draft = updateField(draft, "card", { holds: "other" });
    expect(toFieldSet(draft, 0).fields[1]).toMatchObject({ holds: "other", holds_label: "" });
    draft = updateField(draft, "card", { holds: "tax_id" });
    expect(toFieldSet(draft, 0).fields[1]).toMatchObject({ holds_label: null, sensitive: true });
    draft = updateField(draft, "card", { filled_by: "sender" });
    expect(toFieldSet(draft, 0).fields[1]?.party_id).toBeNull();
  });

  it("keeps boxes on their page and at least 8 points; a click makes a default-size box", () => {
    expect(clampRect([-20, 830, 40, 860], A4)).toEqual([0, 812, 60, 842]); // moved: size kept
    expect(clampRect([100, 100, 102, 101], A4, false)).toEqual([100, 100, 108, 108]);
    expect(clampRect([300, 300, 100, 100], A4, false)).toEqual([100, 100, 300, 300]); // drawn backwards
    expect(boxAt("signature", 300, 400, A4)).toEqual([210, 382, 390, 418]);
    expect(boxAt("checkbox", 2, 2, A4)).toEqual([0, 0, 12, 12]);

    const draft = fromView(VIEW);
    expect(nudge(draft, "card-1", -200, 0, PAGES).fields[1]?.places[0]?.rect).toEqual([0, 100, 100, 120]);
    expect(setRect(draft, "card-1", [10, 10, 600, 30], PAGES, false).fields[1]?.places[0]?.rect).toEqual([10, 10, 595, 30]);
  });

  it("adds, splits, copies and removes places", () => {
    let draft = fromView(VIEW);
    draft = onEveryPage(draft, "card-1", PAGES);
    expect(draft.fields[1]?.places.map((p) => p.page)).toEqual([1, 2, 3]); // page 2 had one already

    const split = splitPlace(draft, "card-2");
    expect(split.draft.fields).toHaveLength(3);
    expect(split.draft.fields[2]).toMatchObject({ id: split.fieldId, label: "Card (2)", key: null, places: [{ id: "card-2" }] });

    draft = deletePlace(split.draft, "card-1");
    expect(draft.fields[1]?.places).toHaveLength(1);
    draft = deletePlace(draft, draft.fields[1]?.places[0]?.id ?? "");
    expect(draft.fields.map((f) => f.id)).not.toContain("card"); // its last place took the field
  });

  it("lets a place hold what its kind allows, and a grouped checkbox its choice", () => {
    // The server's rule (review.values.may_hold): detection groups a PDF's checkboxes into one
    // choice, each standing for an option. The type list offered such a field only "Checkbox".
    const allowed = { checkbox: ["checkbox"], text: ["text", "date"] };
    expect(mayHold(allowed, { kind: "checkbox", option_value: "Individual" }, "choice")).toBe(true);
    expect(mayHold(allowed, { kind: "checkbox", option_value: null }, "choice")).toBe(false);
    expect(mayHold(allowed, { kind: "checkbox", option_value: null }, "checkbox")).toBe(true);
    expect(mayHold(allowed, { kind: "text", option_value: null }, "date")).toBe(true);
    expect(mayHold(allowed, { kind: "radio", option_value: "Gold" }, "choice")).toBe(false); // not in this map
  });

  it("says which field a split shared value joins again when saved", () => {
    // A party gives its signature once: the server folds a second signature field of the same
    // party into the first on Save. "Make separate field" made one, which then vanished unsaid.
    const SHARED = ["signature", "initials", "date_signed", "party_name"];
    const start = fromView(VIEW);
    const signature = updateField(start, "card", { holds: "signature" }); // two places, the client's
    const split = splitPlace(signature, "card-2");
    const made = split.draft.fields.find((f) => f.id === split.fieldId)!;
    expect(joinsOnSave(split.draft, made, SHARED)?.id).toBe("card");
    expect(joinsOnSave(split.draft, split.draft.fields[1]!, SHARED)).toBeNull(); // the first stays
    // Given to someone else, or made another type, it stays apart.
    const other = updateField(split.draft, made.id, { filled_by: "role", party_id: "guarantor" });
    expect(joinsOnSave(other, other.fields.find((f) => f.id === made.id)!, SHARED)).toBeNull();
    const retyped = updateField(split.draft, made.id, { holds: "text" });
    expect(joinsOnSave(retyped, retyped.fields.find((f) => f.id === made.id)!, SHARED)).toBeNull();
  });

  it("reads a condition back exactly as it was written, whatever its option holds", () => {
    // A grouped checkbox's option is named by its own words: "Monthly | Quarterly" was cut at its
    // bar, so the condition named no option and the save was refused.
    const condition = { field_id: "0b9c1d1e-plan", option: "Monthly | Quarterly" };
    expect(conditionOf(conditionKey(condition))).toEqual(condition);
    expect(conditionOf(conditionKey({ field_id: "f", option: "checked" }))).toEqual({ field_id: "f", option: "checked" });
    expect(conditionOf("")).toBeNull(); // "Always asked"
  });

  it("deleting a choice drops the conditions on it", () => {
    const draft = deleteField(fromView(VIEW), "plan");
    expect(draft.fields).toHaveLength(1);
    expect(draft.fields[0]?.depends_on).toBeNull();
  });

  it("orders parties within their group, and asks what becomes of a removed party's fields", () => {
    let draft = fromView(VIEW);
    expect(moveParty(draft, "client", -1)).toBe(draft); // first already
    expect(moveParty(draft, "guarantor", 1)).toBe(draft); // a countersigner is next: not across
    expect(moveParty(draft, "guarantor", -1).parties.map((p) => p.id)).toEqual(["guarantor", "client", "firm"]);

    const added = addParty(draft, { label: "Witness", kind: "signer", kind_label: "Witness" });
    expect(added.draft.parties.map((p) => p.label)).toEqual(["Client", "Guarantor", "Witness", "Firm"]);
    draft = updateParty(added.draft, "firm", { kind: "signer" });
    expect(draft.parties.at(-1)?.id).toBe("firm");

    const moved = removeParty(fromView(VIEW), "client", { kind: "move", to: "guarantor" });
    expect(moved.fields.map((f) => f.party_id)).toEqual(["guarantor", "guarantor"]);
    const none = removeParty(fromView(VIEW), "client", { kind: "none" });
    expect(none.fields.map((f) => [f.filled_by, f.party_id])).toEqual([
      ["none", null],
      ["none", null],
    ]);
    expect(removeParty(fromView(VIEW), "client", { kind: "delete" }).fields).toEqual([]);
  });

  it("undoes and redoes; typing in one box is one step", () => {
    const start = begin(fromView(VIEW));
    let history = apply(start, (d) => updateField(d, "card", { label: "C" }), "label:card");
    history = apply(history, (d) => updateField(d, "card", { label: "Ca" }), "label:card");
    history = apply(history, (d) => updateField(d, "card", { label: "Car" }), "label:card");
    expect(unsaved(history)).toBe(1);
    history = apply(history, (d) => updateField(d, "card", { required: false }));
    expect(unsaved(history)).toBe(2);

    history = undo(history);
    expect(history.present.fields[1]?.required).toBe(true);
    history = undo(history);
    expect(history.present.fields[1]?.label).toBe("Card");
    expect(unsaved(history)).toBe(0);
    history = redo(history);
    expect(history.present.fields[1]?.label).toBe("Car");
    expect(apply(history, (d: Draft) => d)).toBe(history); // nothing changed: no step
  });

  it("a new field is drawn, filled by the chosen party, private by its type", () => {
    const field = newField("tax_id", "Client tax number", "client", { page: 2, rect: [1, 2, 3, 4], option_value: null, option_text: null });
    expect(field).toMatchObject({ filled_by: "role", party_id: "client", sensitive: true, key: null, places: [{ kind: "blank", page: 2 }] });
    expect(newField("text", "Note", null, { page: 1, rect: [1, 2, 3, 4], option_value: null, option_text: null }).filled_by).toBe("none");
  });

  it("sends an Other party's empty words as they are, to be refused and named like a field's", () => {
    let draft = fromView(VIEW);
    draft = updateParty(draft, "firm", { kind_label: "" });
    expect(toFieldSet(draft, 0).parties.find((p) => p.id === "firm")?.kind_label).toBe("");
    draft = updateParty(draft, "firm", { kind_label: " Witness " });
    expect(toFieldSet(draft, 0).parties.find((p) => p.id === "firm")?.kind_label).toBe("Witness");
  });

  it("names a new option after none the choice has, and renaming one is an edit of its field", () => {
    let draft = fromView(VIEW);
    const plan = () => draft.fields.find((f) => f.id === "plan") as DraftField;
    expect(nextOptionName(plan())).toBe("Option 3");
    draft = addPlace(draft, "plan", { page: 1, rect: [1, 1, 13, 13], option_value: "Option 3", option_text: "Option 3" });
    draft = deletePlace(draft, "silver");
    expect(nextOptionName(plan())).toBe("Option 4"); // two places, but "Option 3" is taken

    draft = { ...draft, fields: draft.fields.map((f) => (f.id === "plan" ? { ...f, needs_review: "two answers" } : f)) };
    draft = setOptionText(draft, "gold", "Gold, billed yearly");
    expect(plan().places[0]).toMatchObject({ option_value: "Gold", option_text: "Gold, billed yearly" });
    expect(plan().needs_review).toBeNull();
  });

  it("groups every type for picking exactly once", () => {
    const grouped = HOLD_GROUPS.flatMap((group) => group.holds);
    expect([...grouped].sort()).toEqual(Object.keys(HOLDS).sort());
    expect(new Set(grouped).size).toBe(grouped.length);
  });
});
