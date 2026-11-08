import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { PasswordField } from "./PasswordField";

describe("PasswordField", () => {
  it("hides the password until asked and is labelled for password managers", async () => {
    render(<PasswordField label="Password" autoComplete="new-password" />);
    const input = screen.getByLabelText("Password") as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(input.autocomplete).toBe("new-password");

    await userEvent.setup().click(screen.getByRole("button", { name: "Show password" }));

    expect(input.type).toBe("text");
    expect(screen.getByRole("button", { name: "Hide password" }).getAttribute("aria-pressed")).toBe("true");
  });
});

describe("PasswordField length check", () => {
  function Controlled() {
    const [value, setValue] = useState("");
    return (
      <>
        <PasswordField
          label="New password"
          autoComplete="new-password"
          minLength={12}
          hint="Use 12 or more characters."
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <button type="button">Next</button>
      </>
    );
  }

  it("states the rule up front and flags a short entry only when the field is left", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    const input = screen.getByLabelText("New password");
    expect(screen.getByText("Use 12 or more characters.")).toBeTruthy();

    await user.type(input, "short");
    expect(screen.queryByRole("alert")).toBeNull(); // no nagging while typing

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("alert").textContent).toBe("Use 12 or more characters.");
    expect(input.getAttribute("aria-invalid")).toBe("true");

    await user.type(input, " and longer");
    expect(screen.queryByRole("alert")).toBeNull(); // cleared as soon as it is long enough
  });

  it("does not check the length of a current password", async () => {
    const user = userEvent.setup();
    render(
      <>
        <PasswordField label="Current password" autoComplete="current-password" minLength={12} />
        <button type="button">Next</button>
      </>,
    );
    await user.type(screen.getByLabelText("Current password"), "abc");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
