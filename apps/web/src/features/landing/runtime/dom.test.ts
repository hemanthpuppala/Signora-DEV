import { describe, expect, it } from "vitest";

import { setBusy } from "./dom";

describe("setBusy", () => {
  it("refuses a second start while busy, and restores the button's own content", () => {
    const button = document.createElement("button");
    button.textContent = "Send for signature";

    const restore = setBusy(button, "Sending");
    expect(button).toHaveTextContent("Sending");
    // A second activation (Enter held, or pressed twice) must not run the action again.
    expect(setBusy(button, "Sending")).toBeNull();

    restore?.();
    expect(button).toHaveTextContent("Send for signature");
    expect(button.querySelector(".spin")).toBeNull();
    expect(setBusy(button, "Sending")).not.toBeNull();
  });
});
