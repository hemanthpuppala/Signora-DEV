import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
