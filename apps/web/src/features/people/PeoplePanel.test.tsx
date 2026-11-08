import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import { PeoplePanel } from "./PeoplePanel";

const me = {
  user: { id: "u-owner", email: "rosa@example.com", name: "Rosa Hale" },
  workspace: { id: "w", name: "Hale & Ward LLP" },
  role: { id: "r-editor", key: "read_write", name: "Editor", description: "" },
  display_role: { name: "Owner", description: "" },
  permissions: ["members.manage"],
  is_creator: true,
};
const role = { id: "r-viewer", name: "Viewer", description: "" };
const invite = (id: string, email: string) => ({
  id,
  email,
  role,
  invited_by_name: "Rosa Hale",
  created_at: "2026-11-07T10:00:00Z",
  expires_at: "2026-11-14T10:00:00Z",
  expired: false,
});

function json(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }),
  );
}

describe("PeoplePanel invitations", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    window.sessionStorage.clear();
    fetchMock.mockImplementation((request) => {
      const url = new URL((request as Request).url);
      if (url.pathname === "/api/v1/members") return json([]);
      if (url.pathname === "/api/v1/roles") return json([{ ...role, key: "read", is_system: true, permissions: [] }]);
      if (url.pathname === "/api/v1/invites") return json([invite("inv-a", "a@example.com"), invite("inv-b", "b@example.com")]);
      return Promise.reject(new TypeError("Failed to fetch")); // the resend: connection drops
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("keeps each invitation's pending resend in its own slot", async () => {
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <ToastProvider>
          <PeoplePanel me={me as never} />
        </ToastProvider>
      </QueryClientProvider>,
    );
    const rowA = (await screen.findByText("a@example.com")).closest("tr") as HTMLElement;

    await userEvent.setup().click(within(rowA).getByRole("button", { name: "Resend" }));

    await waitFor(() =>
      expect(window.sessionStorage.getItem("signora:action:invite-resend:inv-a")).not.toBeNull(),
    );
    expect(window.sessionStorage.getItem("signora:action:invite-resend:inv-b")).toBeNull();
    expect(window.sessionStorage.getItem("signora:action:invite-resend")).toBeNull();
  });
});
