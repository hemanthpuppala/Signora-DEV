import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import { DepartmentSettings } from "./DepartmentSettings";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const OWNER = ["members.manage", "members.directory", "departments.manage"];
const EDITOR = ["members.directory", "departments.manage"];
const me = (permissions: string[]) =>
  ({
    user: { id: "u", email: "rosa@example.com", name: "Rosa Hale" },
    workspace: { id: "w", name: "Hale & Ward LLP" },
    role: { id: "r", key: "read_write", name: "Editor", description: "" },
    display_role: { name: "Editor", description: "" },
    permissions,
    is_creator: false,
  }) as never;

const people = [
  { id: "p-1", name: "Ana Diaz", email: "ana@firm.com" },
  { id: "p-2", name: "Ben Ito", email: "ben@firm.com" },
];
const department = (overrides: Record<string, unknown> = {}) => ({
  id: "d-1",
  name: "Finance",
  description: "",
  status: "active",
  created_at: "2026-11-07T10:00:00Z",
  updated_at: "2026-11-07T10:00:00Z",
  archived_at: null,
  counts: { sent: 0, signed: 0, pending: 0 },
  access: "edit",
  created_by: { id: "u", name: "Rosa Hale" },
  settings: { reminder_interval_hours: 24, max_reminders: 5, expiry_days: 14, notify_emails: [] },
  countersigners: [people[0]],
  ...overrides,
});

function reply(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
}

describe("department settings", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const sent: { method: string; path: string; body: unknown }[] = [];

  function serve(current: Record<string, unknown>, onPatch?: () => Promise<Response>) {
    fetchMock.mockImplementation(async (request) => {
      const req = request as Request;
      const path = new URL(req.url).pathname;
      const body = req.method === "GET" ? undefined : await req.clone().json().catch(() => undefined);
      sent.push({ method: req.method, path, body });
      if (path.endsWith("/directory")) return reply(200, people);
      if (path.endsWith("/grants/candidates")) return reply(200, [people[1]]);
      if (path.endsWith("/grants")) return reply(200, []);
      if (path.endsWith("/countersigners")) return reply(200, []);
      if (path.endsWith("/archive")) return reply(200, { ...current, status: "archived" });
      if (req.method === "PATCH" && onPatch) return onPatch();
      return reply(200, current);
    });
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    replace.mockReset();
    sent.length = 0;
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  function open(permissions: string[]) {
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <ToastProvider>
          <DepartmentSettings me={me(permissions)} id="d-1" />
        </ToastProvider>
      </QueryClientProvider>,
    );
  }

  it("shows edit access to the owner only", async () => {
    serve(department());
    open(EDITOR);
    expect(await screen.findByRole("region", { name: "Countersigners" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "People with edit access" })).toBeNull();
  });

  it("adds, reorders and saves countersigners in order", async () => {
    serve(department());
    open(OWNER);
    const section = await screen.findByRole("region", { name: "Countersigners" });
    const user = userEvent.setup();

    await user.click(within(section).getByRole("combobox", { name: "Add a person" }));
    await user.click(await screen.findByRole("option", { name: /Ben Ito/ }));
    await user.click(within(section).getByRole("button", { name: "Add" }));
    const benRow = within(section).getByText("Ben Ito").closest("tr") as HTMLElement;
    await user.click(within(benRow).getByRole("button", { name: "Up" }));
    await user.click(within(section).getByRole("button", { name: "Save countersigners" }));

    await vi.waitFor(() =>
      expect(sent.find((r) => r.method === "PUT" && r.path.endsWith("/countersigners"))?.body).toEqual({
        user_ids: ["p-2", "p-1"],
      }),
    );
  });

  it("shows the server's range error on the timing field", async () => {
    serve(department(), () =>
      reply(422, {
        type: "/problems/validation-failed",
        title: "Some fields are invalid",
        status: 422,
        code: "validation-failed",
        instance: "/x",
        request_id: "r",
        errors: [{ field: "max_reminders", message: "Choose a value from 0 to 20" }],
      }),
    );
    open(EDITOR);
    const user = userEvent.setup();
    const field = await screen.findByLabelText("Max reminders");

    await user.clear(field);
    await user.type(field, "30");
    await user.click(screen.getByRole("button", { name: "Save timing" }));

    expect(await screen.findByText("Choose a value from 0 to 20")).toBeTruthy();
  });

  it("archives only after confirming, then opens the department", async () => {
    serve(department());
    open(EDITOR);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Archive department" }));
    expect(sent.some((r) => r.path.endsWith("/archive"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm archive" }));

    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/departments/d-1"));
  });

  it("asks to restore an archived department before changing it", async () => {
    serve(department({ status: "archived", archived_at: "2026-11-07T12:00:00Z" }));
    open(EDITOR);
    expect(await screen.findByText("Restore this department to change its settings.")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Timing" })).toBeNull();
  });

  it("offers only people a grant would help when giving edit access", async () => {
    serve(department());
    open(OWNER);
    const section = await screen.findByRole("region", { name: "People with edit access" });

    await userEvent.setup().click(within(section).getByRole("combobox", { name: "Add a person" }));

    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Ben Ito · ben@firm.com"]);
  });

  it("adds notify emails one at a time, removes them, and saves the list", async () => {
    serve(department({ settings: { reminder_interval_hours: 24, max_reminders: 5, expiry_days: 14, notify_emails: ["desk@firm.com"] } }));
    open(EDITOR);
    const section = await screen.findByRole("region", { name: "Also notify" });
    const user = userEvent.setup();

    await user.type(within(section).getByLabelText("Email"), "ops@firm.com{Enter}");
    await user.type(within(section).getByLabelText("Email"), "OPS@firm.com");
    await user.click(within(section).getByRole("button", { name: "Add" })); // an exact repeat
    const desk = within(section).getByText("desk@firm.com").closest("tr") as HTMLElement;
    await user.click(within(desk).getByRole("button", { name: "Remove" }));
    await user.click(within(section).getByRole("button", { name: "Save notifications" }));

    await vi.waitFor(() =>
      expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({
        settings: { notify_emails: ["ops@firm.com"] },
      }),
    );
  });

  it("hides the add field once five people are listed", async () => {
    const five = ["a", "b", "c", "d", "e"].map((x) => `${x}@firm.com`);
    serve(department({ settings: { reminder_interval_hours: 24, max_reminders: 5, expiry_days: 14, notify_emails: five } }));
    open(EDITOR);
    const section = await screen.findByRole("region", { name: "Also notify" });
    expect(within(section).queryByLabelText("Email")).toBeNull();
    expect(within(section).queryByRole("button", { name: "Add" })).toBeNull();
  });
});
