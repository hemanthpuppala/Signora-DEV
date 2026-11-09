import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { FormField } from "./api";
import { FieldInput } from "./FieldInput";

const field = (holds: FormField["holds"], label: string): FormField => ({
  id: `f-${holds}`,
  label,
  holds,
  holds_label: null,
  party_id: null,
  required: true,
  sensitive: false,
  options: [],
  depends_on: null,
  places: [],
  from_recipient: null,
});

describe("a date split into boxes", () => {
  it("asks the day and the year as numbers, not as a whole date", () => {
    render(<FieldInput field={field("day", "Effective date: day")} value="" onChange={vi.fn()} />);
    const day = screen.getByLabelText("Effective date: day");
    expect(day.getAttribute("type")).toBe("text");
    expect(day.getAttribute("inputmode")).toBe("numeric");
  });

  it("offers the month by name", async () => {
    const onChange = vi.fn();
    render(<FieldInput field={field("month", "Effective date: month")} value="" onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "December" }));
    expect(onChange).toHaveBeenCalledWith("December");
  });
});
