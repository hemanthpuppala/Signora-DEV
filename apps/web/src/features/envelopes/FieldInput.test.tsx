import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { FormField } from "./api";
import { accepted, FieldInput, refused } from "./FieldInput";

const field = (holds: FormField["holds"], label: string, format: string | null = null): FormField => ({
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
  format,
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
    expect(onChange).toHaveBeenCalledWith("12"); // kept as its number; written as its field says
  });
});

describe("what each type may be typed with", () => {
  it("keeps a day within 1 to 31 and drops letters", () => {
    expect(accepted("day", "9")).toBe("9");
    expect(accepted("day", "31")).toBe("31");
    expect(accepted("day", "32")).toBeNull(); // the keystroke is refused
    expect(accepted("day", "1a")).toBe("1");
    expect(accepted("day", "00")).toBeNull();
  });

  it("drops what a number, an amount, a percentage or a phone cannot hold", () => {
    expect(accepted("number", "12a,5.0-")).toBe("12,5.0-");
    expect(accepted("currency", "$1,200.50")).toBe("1,200.50");
    expect(accepted("percent", "12.5 %x")).toBe("12.5%");
    expect(accepted("phone", "+1 (415) 555-0100 ext")).toBe("+1 (415) 555-0100 ");
    expect(accepted("text", "anything at all")).toBe("anything at all");
  });

  it("asks a year as its blank prints it: two digits after a printed 20", async () => {
    const onChange = vi.fn();
    render(<FieldInput field={field("year", "Year", "YY")} value="" onChange={onChange} />);
    const year = screen.getByLabelText("Year");
    expect(year.getAttribute("maxlength")).toBe("2");
    expect(year.getAttribute("placeholder")).toBe("26");
    expect(year.getAttribute("autocomplete")).toBe("off");
    await userEvent.type(year, "x");
    expect(onChange).toHaveBeenLastCalledWith("");
  });
});

describe("a day or a year the server would refuse", () => {
  it("is named in the server's words; what can be kept is not", () => {
    expect(refused("day", "0")).toBe("Enter a day from 1 to 31");
    expect(refused("day", "31")).toBeUndefined();
    expect(refused("year", "202")).toBe("Enter a year, such as 2026");
    expect(refused("year", "2")).toBe("Enter a year, such as 2026");
    expect(refused("year", "26")).toBeUndefined();
    expect(refused("year", "2026")).toBeUndefined();
    expect(refused("year", "")).toBeUndefined(); // empty is "Required"'s to say
    expect(refused("text", "0")).toBeUndefined();
  });
});
