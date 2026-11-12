import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TopBar } from "./AppShell";

describe("the company in the top bar", () => {
  it("shows the company's logo, named for screen readers, when it has one", () => {
    render(<TopBar workspace="ScoutBoard" workspaceLogo="/api/v1/workspace/logo?v=abc" />);
    const logo = screen.getByRole("img", { name: "ScoutBoard" });
    expect(logo.getAttribute("src")).toBe("/api/v1/workspace/logo?v=abc");
    expect(screen.queryByText("ScoutBoard")).toBeNull();
  });

  it("shows the name when there is no logo", () => {
    render(<TopBar workspace="ScoutBoard" workspaceLogo={null} />);
    expect(screen.getByText("ScoutBoard")).toBeTruthy();
    expect(screen.queryByRole("img", { name: "ScoutBoard" })).toBeNull();
  });

  it("falls back to the name when the logo fails to load", () => {
    render(<TopBar workspace="ScoutBoard" workspaceLogo="/api/v1/workspace/logo?v=abc" />);
    fireEvent.error(screen.getByRole("img", { name: "ScoutBoard" }));
    expect(screen.getByText("ScoutBoard")).toBeTruthy();
  });
});
