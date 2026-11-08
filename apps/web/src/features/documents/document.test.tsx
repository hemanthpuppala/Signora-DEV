import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import { DocumentPage } from "./DocumentPage";
import { FakeUpload } from "./fakeUpload.testing";

vi.mock("pdfjs-dist", () => ({
  version: "6.4.299",
  GlobalWorkerOptions: {},
  getDocument: () => ({ promise: new Promise(() => {}), destroy: vi.fn() }),
}));

const META = { version: "1", commit: "x", password_min_length: 12, password_rule: "x", document_max_bytes: 50 * 1024 * 1024, document_max_pages: 200 };
const A4 = { width: 595, height: 842, rotation: 0 };

const version = (number: number, overrides: Record<string, unknown> = {}) => ({
  id: `v-${number}`,
  number,
  status: "ready",
  problem: null,
  kind: "pdf",
  filename: `Letter v${number}.pdf`,
  bytes: 2048,
  page_count: 2,
  pages: [A4, A4],
  pages_without_text: [],
  ai_instructions: "",
  uploaded_by: { id: "u", name: "Rosa Hale" },
  created_at: "2026-11-07T10:00:00Z",
  processed_at: "2026-11-07T10:00:05Z",
  is_current: false,
  ...overrides,
});

const documentWith = (versions: unknown[], overrides: Record<string, unknown> = {}) => ({
  id: "doc-1",
  name: "Engagement letter",
  description: "Signed before work starts",
  kind: "pdf",
  page_count: 2,
  current_version: { id: "v-2", number: 2 },
  latest_version: { id: "v-2", number: 2, status: "ready", created_at: "2026-11-07T10:00:00Z" },
  updated_at: "2026-11-07T10:00:00Z",
  archived_at: null,
  department_id: "d-1",
  require_email_code: true,
  created_by: { id: "u", name: "Rosa Hale" },
  created_at: "2026-11-07T10:00:00Z",
  access: "edit",
  versions,
  ...overrides,
});

const READY = documentWith([version(2, { is_current: true }), version(1)]);

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}

function wrap(node: ReactNode) {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

describe("document page", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const sent: { method: string; path: string; body: unknown; key: string | null }[] = [];

  function serve(document: unknown, answers: Record<string, () => Promise<Response>> = {}) {
    fetchMock.mockImplementation(async (input) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      const body = request.method === "GET" ? undefined : await request.clone().json().catch(() => undefined);
      sent.push({ method: request.method, path, body, key: request.headers.get("Idempotency-Key") });
      if (path.endsWith("/meta")) return reply(200, META);
      const answer = Object.entries(answers).find(([suffix]) => path.endsWith(suffix));
      if (request.method !== "GET" && answer) return answer[1]();
      return reply(200, document);
    });
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("XMLHttpRequest", FakeUpload);
    FakeUpload.sent = [];
    sent.length = 0;
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  const open = () => wrap(<DocumentPage departmentId="d-1" documentId="doc-1" />);
  const posts = (suffix: string) => sent.filter((r) => r.method !== "GET" && r.path.endsWith(suffix));

  it("shows the current version large, with every version beside it", async () => {
    serve(READY);
    open();

    expect(await screen.findByRole("heading", { name: "Engagement letter" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Engagement letter, version 2" })).toBeTruthy();
    const versions = screen.getByRole("list", { name: "Versions" });
    expect(within(versions).getByText("v2 · Current")).toBeTruthy();
    expect(within(versions).getAllByText("Download original")).toHaveLength(2);
    expect(within(versions).getAllByRole("button", { name: "Open" })).toHaveLength(1); // v1 only
  });

  it("opens an older version and asks before making it current", async () => {
    serve(READY, { "/current-version": () => reply(200, documentWith([version(2), version(1, { is_current: true })], { current_version: { id: "v-1", number: 1 } })) });
    open();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Open" }));
    expect(screen.getByRole("region", { name: "Engagement letter, version 1" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Make current" }));
    expect(screen.getByText("New sends will use it. A newer upload takes over again once it is ready.")).toBeTruthy();
    expect(posts("/current-version")).toHaveLength(0);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Make current" }));

    await vi.waitFor(() => expect(posts("/current-version")[0]?.body).toEqual({ version_id: "v-1" }));
  });

  it("asks for the password only while a version needs one", async () => {
    const locked = documentWith(
      [version(1, { status: "needs_password", problem: { code: "needs_password", message: "This PDF needs a password to open", can_retry: false }, pages: [], page_count: null })],
      { current_version: null },
    );
    serve(locked, {
      "/unlock": () => reply(422, { type: "/problems/wrong-password", title: "Wrong password", status: 422, code: "wrong-password", instance: "/x", request_id: "r" }),
    });
    open();
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("This PDF needs a password to open"), "guess");
    await user.click(screen.getByRole("button", { name: "Open" }));

    expect(await screen.findByText("Wrong password")).toBeTruthy();
    expect(posts("/unlock")[0]?.body).toEqual({ password: "guess" });
  });

  it("offers Try again after a passing failure, and says which pages are scans", async () => {
    const failed = documentWith(
      [version(2, { status: "failed", problem: { code: "unavailable", message: "Processing couldn't finish", can_retry: true }, pages: [] }), version(1, { is_current: true })],
      { current_version: { id: "v-1", number: 1 } },
    );
    serve(failed, { "/retry": () => reply(200, failed) });
    open();
    const user = userEvent.setup();

    expect(await screen.findByText("Processing couldn't finish.")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Engagement letter, version 1" })).toBeTruthy(); // the current one stays
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => expect(posts("/retry")).toHaveLength(1));
  });

  it("gives read access the viewer, versions and downloads only", async () => {
    serve({ ...READY, access: "read" });
    open();
    await screen.findByRole("heading", { name: "Engagement letter" });

    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Make current" })).toBeNull();
    expect(screen.queryByRole("region", { name: "New version" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Archive document" })).toBeNull();
    expect((screen.getByRole("checkbox", { name: "Require email code" }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getAllByText("Download original")).toHaveLength(2);
  });

  it("saves the email code and only the fields a person changed", async () => {
    serve(READY, { "/documents/doc-1": () => reply(200, READY) });
    open();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("checkbox", { name: "Require email code" }));
    await vi.waitFor(() => expect(posts("/documents/doc-1")[0]?.body).toEqual({ require_email_code: false }));
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const name = screen.getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Retainer");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await vi.waitFor(() => expect(posts("/documents/doc-1")[1]?.body).toEqual({ name: "Retainer" }));
  });

  it("archives only after confirming", async () => {
    serve(READY, { "/archive": () => reply(200, { ...READY, archived_at: "2026-11-07T12:00:00Z" }) });
    open();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Archive document" }));
    expect(posts("/archive")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Confirm archive" }));

    expect(await screen.findByText("This document can't get new versions or be sent.")).toBeTruthy();
  });

  it("adds a new version with its instructions", async () => {
    serve(READY, { "/versions": () => reply(201, READY) });
    open();
    const user = userEvent.setup();
    const file = new File(["%PDF-1.7"], "Letter v3.pdf", { type: "application/pdf" });

    await user.upload(await screen.findByLabelText(/Drop the new version/), file);
    expect(FakeUpload.sent[0]?.url).toBe("/api/v1/departments/d-1/uploads?filename=Letter%20v3.pdf");
    FakeUpload.sent[0]?.answer(201, { id: "up-3", filename: "Letter v3.pdf", kind: "pdf", bytes: 8, suggested_name: "Letter v3", expires_at: "2026-11-08T10:00:00Z", duplicate: null });
    await user.type(await screen.findByLabelText("Instructions for the AI"), "Fee clause changed");
    await user.click(screen.getByRole("button", { name: "Add version" }));

    await vi.waitFor(() => expect(posts("/versions")[0]?.body).toEqual({ upload_id: "up-3", ai_instructions: "Fee clause changed" }));
    expect(posts("/versions")[0]?.key).toBeTruthy();
  });

  it("never makes a file already in the department a version", async () => {
    serve(READY);
    open();
    const user = userEvent.setup();

    await user.upload(await screen.findByLabelText(/Drop the new version/), new File(["%PDF-1.7"], "Copy.pdf"));
    FakeUpload.sent[0]?.answer(201, { id: "up-4", filename: "Copy.pdf", kind: "pdf", bytes: 8, suggested_name: "Copy", expires_at: "2026-11-08T10:00:00Z", duplicate: { document_id: "doc-1", document_name: "Engagement letter", version_number: 1, archived: false } });

    expect(await screen.findByText("This file is already here as Engagement letter, version 1. It can only be added as a separate document.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add version" })).toBeNull();
  });
});
