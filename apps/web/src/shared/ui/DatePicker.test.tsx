import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { DatePicker, typedDate } from "./DatePicker";

function Field({ start = "" }: { start?: string }) {
  const [value, setValue] = useState(start);
  return (
    <>
      <DatePicker label="Effective date" value={value} onChange={setValue} />
      <output data-testid="value">{value}</output>
    </>
  );
}

describe("the date picker", () => {
  it("takes a typed date, month first or as YYYY-MM-DD, and keeps it as YYYY-MM-DD", () => {
    expect(typedDate("12/1/2026")).toBe("2026-12-01");
    expect(typedDate("2026-12-01")).toBe("2026-12-01");
    expect(typedDate("2/30/2026")).toBeNull(); // no 30th of February
    expect(typedDate("13/01/2026")).toBeNull();
    expect(typedDate("12/01")).toBeNull();
  });

  it("passes on a date being typed as it is, then the whole date", async () => {
    render(<Field />);
    const user = userEvent.setup();
    const box = screen.getByLabelText("Effective date");

    await user.type(box, "12/01");
    expect(screen.getByTestId("value").textContent).toBe("12/01");
    await user.type(box, "/2026");
    expect(screen.getByTestId("value").textContent).toBe("2026-12-01");
  });

  it("chooses a day from the calendar, moved through with the keyboard", async () => {
    render(<Field start="2026-11-11" />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Choose Effective date from a calendar" }));
    const today = await screen.findByRole("gridcell", { name: "November 11, 2026" });
    expect(today.getAttribute("aria-selected")).toBe("true");
    await user.keyboard("{ArrowRight}{ArrowDown}{Enter}"); // a day on, then a week on

    expect(screen.getByTestId("value").textContent).toBe("2026-11-19");
    expect((screen.getByLabelText("Effective date") as HTMLInputElement).value).toBe("11/19/2026");
  });
});
