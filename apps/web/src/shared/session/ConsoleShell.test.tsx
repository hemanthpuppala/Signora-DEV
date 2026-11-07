import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import { ConsoleShell } from "./ConsoleShell";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/people",
}));

const me = (permissions: string[], isCreator = false) => ({
  user: { id: "u", email: "rosa@example.com", name: "Rosa Hale" },
  workspace: { id: "w", name: "Hale & Ward LLP" },
  role: { id: "r", key: "read_write", name: "Read/write" },
  permissions,
  is_creator: isCreator,
});

function serve(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
}

function renderShell(requires?: "members.manage") {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <ToastProvider>
        <ConsoleShell {...(requires ? { requires } : {})}>{(user) => <p>Hello {user.user.name}</p>}</ConsoleShell>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ConsoleShell", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    replace.mockReset();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("shows People in the navigation only with members.manage", async () => {
    fetchMock.mockImplementation(() => serve(200, me(["members.manage", "workspace.rename"], true)));
    renderShell();
    expect(await screen.findByText("Hello Rosa Hale")).toBeTruthy();
    expect(screen.getByRole("link", { name: "People" })).toBeTruthy();
    expect(screen.getByText("Hale & Ward LLP")).toBeTruthy();
  });

  it("hides People and its page from read/write members", async () => {
    fetchMock.mockImplementation(() => serve(200, me(["members.directory", "workspace.rename"])));
    renderShell("members.manage");
    expect(await screen.findByText("No access")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "People" })).toBeNull();
    expect(screen.queryByText("Hello Rosa Hale")).toBeNull();
  });

  it("sends a signed-out visitor to log in, keeping the page to return to", async () => {
    fetchMock.mockImplementation(() =>
      serve(401, {
        type: "/problems/unauthenticated",
        title: "Please sign in",
        status: 401,
        code: "unauthenticated",
        instance: "/api/v1/me",
        request_id: "r",
      }),
    );
    renderShell();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?next=%2Fpeople"));
  });
});
