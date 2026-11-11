import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Landing } from "./Landing";

// The demos need a real browser (canvas, WebGL, layout); this file checks the markup they act on.
vi.mock("./LandingRuntime", () => ({ LandingRuntime: () => null }));

const hrefs = (name: string) =>
  screen.getAllByRole("link", { name }).map((link) => link.getAttribute("href"));

describe("Landing", () => {
  it("offers sign-up and log-in to a visitor without a session", () => {
    render(<Landing signedIn={false} />);
    // Header, hero and closing section; the footer does not repeat them.
    expect(hrefs("Sign up")).toEqual(["/signup", "/signup", "/signup"]);
    // The header (the phone menu's copy is hidden until opened, so not counted).
    expect(hrefs("Sign in")).toEqual(["/login"]);
    expect(screen.queryByRole("link", { name: "Open workspace" })).toBeNull();
  });

  it("opens the workspace for a signed-in visitor, and offers no sign-in", () => {
    render(<Landing signedIn />);
    expect(hrefs("Open workspace")).toEqual(["/departments", "/departments", "/departments"]);
    expect(screen.queryByRole("link", { name: "Sign up" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
  });

  it("links the header to every section on the page", () => {
    const { container } = render(<Landing signedIn={false} />);
    const links = within(screen.getByRole("navigation", { name: "Sections" })).getAllByRole("link");
    const targets = links.map((link) => link.getAttribute("href")).filter((href) => href?.startsWith("#"));
    expect(targets).toEqual(["#templates", "#extract", "#how", "#sign", "#firm"]);
    for (const target of targets) expect(container.querySelector(target ?? "")).not.toBeNull();
  });

  it("carries no style attributes, which the Content Security Policy would block", () => {
    const { container } = render(<Landing signedIn={false} />);
    expect(container.querySelectorAll("[style]")).toHaveLength(0);
  });
});
