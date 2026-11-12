import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import { SettingsPanel } from "./SettingsPanel";

const ALL = ["workspace.rename"];
const me = (isCreator: boolean, website: string | null = null) =>
  ({
    user: { id: "u", email: "ana@scoutboard.com", name: "Ana" },
    workspace: { id: "w", name: "ScoutBoard", website, logo_url: null },
    role: { id: "r", key: "read_write", name: "Editor", description: "" },
    display_role: { name: isCreator ? "Owner" : "Editor", description: "" },
    permissions: ALL,
    is_creator: isCreator,
  }) as never;

function reply(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
}

function show(who: never) {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <ToastProvider>
        <SettingsPanel me={who} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("the company's website in Settings", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("is the owner's alone", () => {
    show(me(false));
    expect(screen.getByLabelText("Company name")).toBeTruthy();
    expect(screen.queryByLabelText("Company website")).toBeNull();
  });

  it("shows the owner the website kept, and saves a new one", async () => {
    const sent: unknown[] = [];
    fetchMock.mockImplementation(async (request) => {
      const req = request as Request;
      if (req.method === "PUT") {
        sent.push(await req.json());
        return reply(200, { id: "w", name: "ScoutBoard", website: "scoutboard.com", logo_url: null });
      }
      return new Promise<Response>(() => {});
    });
    show(me(true, "old.com"));
    const field = screen.getByLabelText("Company website");
    expect((field as HTMLInputElement).value).toBe("old.com");

    const user = userEvent.setup();
    await user.clear(field);
    await user.type(field, "https://www.scoutboard.com");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sent).toEqual([{ website: "https://www.scoutboard.com" }]));
    expect(await screen.findByText("Website saved")).toBeTruthy();
    expect((field as HTMLInputElement).value).toBe("scoutboard.com");
  });

  it("removes the website when the field is emptied", async () => {
    const sent: unknown[] = [];
    fetchMock.mockImplementation(async (request) => {
      const req = request as Request;
      if (req.method === "PUT") {
        sent.push(await req.json());
        return reply(200, { id: "w", name: "ScoutBoard", website: null, logo_url: null });
      }
      return new Promise<Response>(() => {});
    });
    show(me(true, "scoutboard.com"));
    const user = userEvent.setup();
    await user.clear(screen.getByLabelText("Company website"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sent).toEqual([{ website: null }]));
    expect(await screen.findByText("Website removed")).toBeTruthy();
  });
});
