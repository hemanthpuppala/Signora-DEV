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

const grantOf = (id: string) => {
  const person = people.find((p) => p.id === id) as (typeof people)[number];
  return {
    user: { id: person.id, name: person.name },
    email: person.email,
    granted_by: { id: "u", name: "Rosa Hale" },
    created_at: "2026-11-07T10:00:00Z",
  };
};

describe("department settings", () => {
  const fetchMock = vi.fn<typeof fetch>();
  /** What the server holds now; tests change it to play another manager's edits. */
  const server: { grants: string[] } = { grants: [] };
  const sent: { method: string; path: string; body: unknown }[] = [];

  function serve(current: Record<string, unknown>, onPatch?: () => Promise<Response>) {
    fetchMock.mockImplementation(async (request) => {
      const req = request as Request;
      const path = new URL(req.url).pathname;
      const body = req.method === "GET" ? undefined : await req.clone().json().catch(() => undefined);
      sent.push({ method: req.method, path, body });
      if (path.endsWith("/directory")) return reply(200, people);
      if (path.endsWith("/grants/candidates")) return reply(200, [people[1]]);
      if (path.endsWith("/grants")) {
        if (req.method === "PUT") server.grants = (body as { user_ids: string[] }).user_ids;
        return reply(200, server.grants.map(grantOf));
      }
      if (path.endsWith("/countersigners")) {
        const ids = (body as { user_ids: string[] }).user_ids;
        return reply(200, ids.map((id) => people.find((p) => p.id === id)));
      }
      if (path.endsWith("/archive")) return reply(200, { ...current, status: "archived" });
      if (req.method === "PATCH" && onPatch) return onPatch();
      return reply(200, current);
    });
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    replace.mockReset();
    sent.length = 0;
    server.grants = [];
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  function open(permissions: string[], client = makeQueryClient()) {
    return render(
      <QueryClientProvider client={client}>
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

  it("saves countersigners as they are added and reordered", async () => {
    serve(department());
    open(OWNER);
    const section = await screen.findByRole("region", { name: "Countersigners" });
    const user = userEvent.setup();
    const lastPut = () => sent.filter((r) => r.path.endsWith("/countersigners")).at(-1)?.body;

    await user.click(within(section).getByRole("combobox", { name: "Add a person" }));
    await user.click(await screen.findByRole("option", { name: /Ben Ito/ }));
    await user.click(within(section).getByRole("button", { name: "Add" }));
    await vi.waitFor(() => expect(lastPut()).toEqual({ user_ids: ["p-1", "p-2"] }));

    const benRow = (await within(section).findByText("Ben Ito")).closest("tr") as HTMLElement;
    await user.click(within(benRow).getByRole("button", { name: "Up" }));
    await vi.waitFor(() => expect(lastPut()).toEqual({ user_ids: ["p-2", "p-1"] }));
    expect(within(section).queryByRole("button", { name: /save/i })).toBeNull();
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

  it("saves each added or removed notify email straight away", async () => {
    serve(department({ settings: { reminder_interval_hours: 24, max_reminders: 5, expiry_days: 14, notify_emails: ["desk@firm.com"] } }));
    open(EDITOR);
    const section = await screen.findByRole("region", { name: "Also notify" });
    const user = userEvent.setup();

    await user.type(within(section).getByLabelText("Email"), "ops@firm.com{Enter}");
    await vi.waitFor(() =>
      expect(sent.filter((r) => r.method === "PATCH").at(-1)?.body).toEqual({
        settings: { notify_emails: ["desk@firm.com", "ops@firm.com"] },
      }),
    );

    const desk = within(section).getByText("desk@firm.com").closest("tr") as HTMLElement;
    await user.click(within(desk).getByRole("button", { name: "Remove" }));
    await vi.waitFor(() => expect(sent.filter((r) => r.method === "PATCH")).toHaveLength(2));
    expect(within(section).queryByRole("button", { name: /save/i })).toBeNull();
  });

  it("refuses a malformed address before saving", async () => {
    serve(department());
    open(EDITOR);
    const section = await screen.findByRole("region", { name: "Also notify" });
    const user = userEvent.setup();

    await user.type(within(section).getByLabelText("Email"), "hiaf{Enter}");

    expect(await within(section).findByText("Enter a valid email address")).toBeTruthy();
    expect(sent.some((r) => r.method === "PATCH")).toBe(false);
  });

  it("hides the add field once five people are listed", async () => {
    const five = ["a", "b", "c", "d", "e"].map((x) => `${x}@firm.com`);
    serve(department({ settings: { reminder_interval_hours: 24, max_reminders: 5, expiry_days: 14, notify_emails: five } }));
    open(EDITOR);
    const section = await screen.findByRole("region", { name: "Also notify" });
    expect(within(section).queryByLabelText("Email")).toBeNull();
    expect(within(section).queryByRole("button", { name: "Add" })).toBeNull();
  });

  it("shows saved edit access when the page is opened again", async () => {
    serve(department());
    const client = makeQueryClient();
    const first = open(OWNER, client);
    const user = userEvent.setup();
    const section = await screen.findByRole("region", { name: "People with edit access" });
    await user.click(within(section).getByRole("combobox", { name: "Add a person" }));
    await user.click(await screen.findByRole("option", { name: /Ben Ito/ }));
    await user.click(within(section).getByRole("button", { name: "Add" }));
    await vi.waitFor(() => expect(server.grants).toEqual(["p-2"]));
    first.unmount();

    open(OWNER, client); // same cache, as when coming back to the page

    const again = await screen.findByRole("region", { name: "People with edit access" });
    expect(within(again).getByText("Ben Ito")).toBeTruthy();
  });

  it("shows another manager's countersigner change without a reload", async () => {
    let current = department();
    fetchMock.mockImplementation(async (request) => {
      const path = new URL((request as Request).url).pathname;
      if (path.endsWith("/directory")) return reply(200, people);
      if (path.includes("/grants")) return reply(200, []);
      return reply(200, current);
    });
    const client = makeQueryClient();
    open(EDITOR, client);
    const section = await screen.findByRole("region", { name: "Countersigners" });
    expect(within(section).queryByText("Ben Ito")).toBeNull();

    current = department({ countersigners: people }); // another manager adds Ben
    await client.invalidateQueries({ queryKey: ["department", "d-1"] }); // e.g. window focus

    expect(await within(section).findByText("Ben Ito")).toBeTruthy();
  });

  it("sends only the fields this person changed and shows a colleague's change", async () => {
    let current = department({ description: "Old" });
    const patches: unknown[] = [];
    fetchMock.mockImplementation(async (request) => {
      const req = request as Request;
      const path = new URL(req.url).pathname;
      if (path.endsWith("/directory")) return reply(200, people);
      if (path.includes("/grants")) return reply(200, []);
      if (req.method === "PATCH") patches.push(await req.clone().json());
      return reply(200, current);
    });
    const client = makeQueryClient();
    open(EDITOR, client);
    const user = userEvent.setup();
    const name = await screen.findByLabelText("Name");
    const expiry = screen.getByLabelText("Expires after (days)");

    current = department({ description: "Set by a colleague", settings: { ...department().settings, max_reminders: 3 } });
    await client.invalidateQueries({ queryKey: ["department", "d-1"] });
    expect(await screen.findByDisplayValue("Set by a colleague")).toBeTruthy(); // untouched field follows
    expect((screen.getByLabelText("Max reminders") as HTMLInputElement).value).toBe("3");

    await user.clear(name);
    await user.type(name, "Accounts");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.clear(expiry);
    await user.type(expiry, "30");
    await user.click(screen.getByRole("button", { name: "Save timing" }));

    await vi.waitFor(() =>
      expect(patches).toEqual([{ name: "Accounts" }, { settings: { expiry_days: 30 } }]),
    );
  });

  it("adds a notify email to the latest saved list", async () => {
    const withEmails = (notify_emails: string[]) =>
      department({ settings: { ...department().settings, notify_emails } });
    let current = withEmails(["desk@firm.com"]);
    const patches: unknown[] = [];
    fetchMock.mockImplementation(async (request) => {
      const req = request as Request;
      const path = new URL(req.url).pathname;
      if (path.endsWith("/directory")) return reply(200, people);
      if (path.includes("/grants")) return reply(200, []);
      if (req.method === "PATCH") patches.push(await req.clone().json());
      return reply(200, current);
    });
    const client = makeQueryClient();
    open(EDITOR, client);
    const section = await screen.findByRole("region", { name: "Also notify" });

    current = withEmails(["desk@firm.com", "audit@firm.com"]); // a colleague adds one
    await client.invalidateQueries({ queryKey: ["department", "d-1"] });
    expect(await within(section).findByText("audit@firm.com")).toBeTruthy();

    await userEvent.setup().type(within(section).getByLabelText("Email"), "ops@firm.com{Enter}");

    await vi.waitFor(() =>
      expect(patches).toEqual([
        { settings: { notify_emails: ["desk@firm.com", "audit@firm.com", "ops@firm.com"] } },
      ]),
    );
  });
});
