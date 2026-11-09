import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import { DepartmentPage } from "./DepartmentPage";
import { DepartmentsHome } from "./DepartmentsHome";
import { NewDepartmentForm } from "./NewDepartmentForm";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(search),
}));

const EDITOR = ["departments.create", "departments.manage", "documents.send", "documents.view_sends"];
const me = (permissions: string[]) =>
  ({
    user: { id: "u", email: "rosa@example.com", name: "Rosa Hale" },
    workspace: { id: "w", name: "Hale & Ward LLP" },
    role: { id: "r", key: "read_write", name: "Editor", description: "" },
    display_role: { name: "Editor", description: "" },
    permissions,
    is_creator: false,
  }) as never;

const finance = {
  id: "d-1",
  name: "Finance",
  description: "Engagement letters",
  status: "active",
  created_at: "2026-11-07T10:00:00Z",
  updated_at: "2026-11-07T10:00:00Z",
  archived_at: null,
  counts: { sent: 4, signed: 3, pending: 1 },
  access: "edit",
  created_by: { id: "u", name: "Rosa Hale" },
  settings: { reminder_interval_hours: 24, max_reminders: 5, expiry_days: 14, notify_emails: [] },
  countersigners: [],
};

function reply(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
}

function problem(code: string, status: number) {
  return { type: `/problems/${code}`, title: code, status, code, instance: "/x", request_id: "r" };
}

function wrap(node: ReactNode) {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

describe("departments screens", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    replace.mockReset();
    search = "";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("shows departments as cards with their counts, and an add card for editors", async () => {
    fetchMock.mockImplementation(() => reply(200, [finance]));
    wrap(<DepartmentsHome me={me(EDITOR)} />);

    const card = await screen.findByRole("link", { name: /Finance/ });
    expect(card.getAttribute("href")).toBe("/departments/d-1");
    expect(card.textContent).toContain("Engagement letters");
    expect(card.textContent).toMatch(/Sent\s*4/);
    expect(screen.getAllByRole("link", { name: /New department/ })).toHaveLength(2);
  });

  it("shows viewers no create action at all, and the empty state", async () => {
    fetchMock.mockImplementation(() => reply(200, []));
    wrap(<DepartmentsHome me={me([])} />);

    expect(await screen.findByText("No departments yet.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /New department/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /New department/ })).toBeNull();
    expect(screen.queryByText(/Only owners and editors/)).toBeNull();
  });

  it("points a taken name at the name field", async () => {
    fetchMock.mockImplementation(() => reply(409, problem("department-name-taken", 409)));
    const onCreated = vi.fn();
    wrap(<NewDepartmentForm onCreated={onCreated} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Name"), "Finance");
    await user.click(screen.getByRole("button", { name: /create department/i }));

    expect(await screen.findByText("Another department already has this name.")).toBeTruthy();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("reports the new department after creating it", async () => {
    fetchMock.mockImplementation(() => reply(201, finance));
    const onCreated = vi.fn();
    wrap(<NewDepartmentForm onCreated={onCreated} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Name"), "Finance");
    await user.click(screen.getByRole("button", { name: /create department/i }));

    await vi.waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: "d-1" }), null));
    expect(screen.queryByRole("region", { name: "Documents" })).toBeNull(); // no upload: no dropzone
  });

  it("holds one dropped file until the department exists, then hands it over", async () => {
    fetchMock.mockImplementation(() => reply(201, finance));
    const onCreated = vi.fn();
    wrap(<NewDepartmentForm onCreated={onCreated} upload={{ hint: "up to 50 MB" }} />);
    const user = userEvent.setup();
    const letter = new File(["%PDF-1.7"], "Letter.pdf", { type: "application/pdf" });
    const nda = new File(["%PDF-1.7"], "NDA.pdf", { type: "application/pdf" });

    await user.upload(screen.getByLabelText(/Drop a PDF or Word file/), nda);
    expect(screen.queryByLabelText(/Drop a PDF or Word file/)).toBeNull(); // one at a time: the file takes its place
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await user.upload(screen.getByLabelText(/Drop a PDF or Word file/), letter);
    expect(screen.getByRole("region", { name: "Document to upload" })).toBeTruthy();
    await user.type(screen.getByLabelText("Name"), "Finance");
    await user.click(screen.getByRole("button", { name: /create department/i }));

    await vi.waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: "d-1" }), letter));
    const urls = fetchMock.mock.calls.map(([request]) => (request as Request).url);
    expect(urls.some((url) => url.includes("/uploads"))).toBe(false); // nothing is sent early
  });

  it("shows an archived department read-only, with Restore for those who manage", async () => {
    const archived = { ...finance, status: "archived", archived_at: "2026-11-07T12:00:00Z" };
    fetchMock.mockImplementation(() => reply(200, archived));
    wrap(
      <DepartmentPage me={me(EDITOR)} id="d-1" tab="documents" documentCount={2}>
        {(department) => <p>{`documents of ${department.name}, ${department.status}`}</p>}
      </DepartmentPage>,
    );

    expect(await screen.findByText(/Archived on .*Restore it to make changes\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Restore" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add envelope" })).toBeNull();
    expect(screen.getByText("documents of Finance, archived")).toBeTruthy(); // the open tab's content
    const tabs = screen.getByRole("navigation", { name: "Department" });
    expect(within(tabs).getByRole("link", { name: "Documents · 2" }).getAttribute("aria-current")).toBe("page");
    expect(within(tabs).getByRole("link", { name: "Envelopes" }).getAttribute("href")).toBe("/departments/d-1");
  });

  it("gives viewers no settings or restore", async () => {
    fetchMock.mockImplementation(() => reply(200, { ...finance, access: "read" }));
    wrap(
      <DepartmentPage me={me([])} id="d-1" tab="envelopes">
        {() => null}
      </DepartmentPage>,
    );

    expect(await screen.findByRole("heading", { name: "Finance" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull();
  });

  it("says when a department does not exist", async () => {
    fetchMock.mockImplementation(() => reply(404, problem("not-found", 404)));
    wrap(
      <DepartmentPage me={me(EDITOR)} id="nope" tab="envelopes">
        {() => null}
      </DepartmentPage>,
    );
    expect(await screen.findByText("This department doesn't exist.")).toBeTruthy();
  });
});
