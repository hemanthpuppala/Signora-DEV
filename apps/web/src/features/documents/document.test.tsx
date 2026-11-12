import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import { DocumentPage } from "./DocumentPage";
import { FakeUpload } from "./fakeUpload.testing";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

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
  field_count: 0,
  name: null,
  description: null,
  derived_from: null,
  approved: null,
  is_current: false,
  ...overrides,
});

const APPROVAL = { by: { id: "u", name: "Rosa Hale" }, at: "2026-11-08T10:00:00Z" };
const approvedVersion = (number: number, overrides: Record<string, unknown> = {}) =>
  version(number, { status: "approved", approved: APPROVAL, ...overrides });

const documentWith = (versions: unknown[], overrides: Record<string, unknown> = {}) => ({
  id: "doc-1",
  name: "Engagement letter",
  description: "Signed before work starts",
  kind: "pdf",
  page_count: 2,
  current_version: { id: "v-2", number: 2 },
  latest_version: { id: "v-2", number: 2, status: "ready", created_at: "2026-11-07T10:00:00Z", field_count: 0 },
  updated_at: "2026-11-07T10:00:00Z",
  archived_at: null,
  department_id: "d-1",
  created_by: { id: "u", name: "Rosa Hale" },
  created_at: "2026-11-07T10:00:00Z",
  access: "edit",
  versions,
  ...overrides,
});

const READY = documentWith([version(2, { is_current: true }), version(1)]);

const TEXTUAL = ["signature", "initials", "date_signed", "full_name", "email", "tax_id", "date", "text", "note", "other"];

const NO_FIELDS = {
  status: "ready",
  stage: "done",
  fields_from: "form_fields",
  roles: [],
  fields: [],
  pending: [],
  flags: { no_fields: false, addressed_to_ai: false, xfa: false, already_signed: false, repaired: false },
  revision: 0,
  warnings: [],
  allowed: { text: TEXTUAL, blank: [...TEXTUAL, "checkbox", "choice"], signature: ["signature", "initials"], checkbox: ["checkbox"], radio: ["choice"], combobox: ["choice"], listbox: ["choice"] },
};

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

  function serve(document: unknown, answers: Record<string, () => Promise<Response>> = {}, fields: unknown = NO_FIELDS) {
    fetchMock.mockImplementation(async (input) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      const body = request.method === "GET" ? undefined : await request.clone().json().catch(() => undefined);
      sent.push({ method: request.method, path, body, key: request.headers.get("Idempotency-Key") });
      if (path.endsWith("/meta")) return reply(200, META);
      if (path.endsWith("/fields")) return reply(200, fields);
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
    serve(documentWith([approvedVersion(2, { is_current: true }), approvedVersion(1)]));
    open();

    expect(await screen.findByRole("heading", { name: "Engagement letter" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Engagement letter, version 2" })).toBeTruthy();
    const versions = screen.getByRole("list", { name: "Versions" });
    expect(within(versions).getByText("V2")).toBeTruthy();
    expect(within(versions).getAllByRole("img", { name: "Current" })).toHaveLength(1); // a star on the current one only
    expect(within(versions).getAllByRole("link", { name: "Download original" })).toHaveLength(2); // an icon, named
    expect(within(versions).getAllByRole("button", { name: "Open" })).toHaveLength(1); // v1 only
    expect(within(versions).getAllByRole("button", { name: "Make current" })).toHaveLength(1); // a star on v1 only
  });

  it("opens an older version and asks before making it current", async () => {
    serve(documentWith([approvedVersion(2, { is_current: true }), approvedVersion(1)]), {
      "/current-version": () =>
        reply(200, documentWith([approvedVersion(2), approvedVersion(1, { is_current: true })], { current_version: { id: "v-1", number: 1 } })),
    });
    open();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Open" }));
    expect(screen.getByRole("region", { name: "Engagement letter, version 1" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Make current" }));
    expect(screen.getByText("New sends will use it. A newer version takes over again once it is approved.")).toBeTruthy();
    expect(posts("/current-version")).toHaveLength(0);
    // The dialog opens (showModal) in an effect: wait for it before using its buttons.
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Make current" }));

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
    // the way back is the eyebrow itself ("‹ Documents"), so everyone has it
    expect(screen.getByRole("link", { name: "Back to Templates" }).getAttribute("href")).toBe("/departments/d-1/documents");
    expect(screen.queryByRole("button", { name: "Make current" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New version" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Archive template" })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Require email code" })).toBeNull(); // a send's setting (Phase 7)
    expect(screen.getAllByRole("link", { name: "Download original" })).toHaveLength(2);
  });

  it("saves only the fields a person changed", async () => {
    serve(READY, { "/documents/doc-1": () => reply(200, READY) });
    open();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const name = screen.getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Retainer");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await vi.waitFor(() => expect(posts("/documents/doc-1")[0]?.body).toEqual({ name: "Retainer" }));
  });

  it("archives only after confirming", async () => {
    serve(READY, { "/archive": () => reply(200, { ...READY, archived_at: "2026-11-07T12:00:00Z" }) });
    open();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Archive template" }));
    expect(posts("/archive")).toHaveLength(0);
    await user.click(within(await screen.findByRole("dialog", { name: "Archive this template?" })).getByRole("button", { name: "Confirm archive" }));

    expect(await screen.findByText("This template can't get new versions or be sent.")).toBeTruthy();
  });

  it("uploads a new version as soon as it is picked, then takes the AI's instructions before adding it", async () => {
    serve(READY, { "/versions": () => reply(201, READY) });
    open();
    const user = userEvent.setup();
    const file = new File(["%PDF-1.7"], "Letter v3.pdf", { type: "application/pdf" });

    await user.upload(await screen.findByLabelText("New version file"), file);
    expect(FakeUpload.sent[0]?.url).toBe("/api/v1/departments/d-1/uploads?filename=Letter%20v3.pdf");
    expect(screen.getByRole("list", { name: "New version: Upload" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "New version" }) as HTMLButtonElement).disabled).toBe(true); // one at a time
    FakeUpload.sent[0]?.answer(201, { id: "up-3", filename: "Letter v3.pdf", kind: "pdf", bytes: 8, suggested_name: "Letter v3", expires_at: "2026-11-08T10:00:00Z", duplicate: null });

    // Review fix: the rework posted the version with no instructions; the facts given for the
    // first version (who countersigns) were lost on every later one.
    const form = await screen.findByRole("form", { name: "New version" });
    expect(posts("/versions")).toHaveLength(0);
    await user.type(within(form).getByLabelText("Instructions for the AI"), "The firm countersigns.");
    await user.click(within(form).getByRole("button", { name: "Add version" }));
    await vi.waitFor(() => expect(posts("/versions")[0]?.body).toEqual({ upload_id: "up-3", ai_instructions: "The firm countersigns." }));
    expect(posts("/versions")[0]?.key).toBeTruthy();
    await vi.waitFor(() => expect(screen.queryByRole("form", { name: "New version" })).toBeNull());
  });

  it("lets the person drop an uploaded file instead of adding it", async () => {
    serve(READY);
    open();
    const user = userEvent.setup();

    await user.upload(await screen.findByLabelText("New version file"), new File(["%PDF-1.7"], "Letter v3.pdf"));
    FakeUpload.sent[0]?.answer(201, { id: "up-3", filename: "Letter v3.pdf", kind: "pdf", bytes: 8, suggested_name: "Letter v3", expires_at: "2026-11-08T10:00:00Z", duplicate: null });
    await user.click(within(await screen.findByRole("form", { name: "New version" })).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("form", { name: "New version" })).toBeNull();
    expect((screen.getByRole("button", { name: "New version" }) as HTMLButtonElement).disabled).toBe(false);
    expect(posts("/versions")).toHaveLength(0);
  });

  it("shows a new version's steps until it is ready", async () => {
    serve(documentWith([version(3, { status: "processing", processed_at: null }), version(2, { is_current: true }), version(1)]));
    open();

    expect(await screen.findByRole("list", { name: "New version: Process" })).toBeTruthy();
  });

  it("never makes a file already in the department a version", async () => {
    serve(READY);
    open();
    const user = userEvent.setup();

    await user.upload(await screen.findByLabelText("New version file"), new File(["%PDF-1.7"], "Copy.pdf"));
    FakeUpload.sent[0]?.answer(201, { id: "up-4", filename: "Copy.pdf", kind: "pdf", bytes: 8, suggested_name: "Copy", expires_at: "2026-11-08T10:00:00Z", duplicate: { document_id: "doc-1", document_name: "Engagement letter", version_number: 1, archived: false } });

    expect(await screen.findByText("This file is already here as Engagement letter, version 1. It can only be added as a separate template.")).toBeTruthy();
    expect(posts("/versions")).toHaveLength(0);
  });

  describe("fields", () => {
    let places = 0;
    const placement = (page: number, y: number, extra: Record<string, unknown> = {}) => ({
      id: `place-${(places += 1)}`,
      page,
      rect: [100, y, 300, y + 20],
      kind: "text",
      option_value: null,
      option_text: null,
      ...extra,
    });
    const field = (key: string, label: string, extra: Record<string, unknown> = {}) => ({
      id: `id-${key}`,
      key,
      label,
      holds: "text",
      holds_label: null,
      filled_by: "sender",
      role: null,
      party_id: typeof extra.role === "string" ? `party-${extra.role}` : null,
      origin: "detected",
      required: true,
      sensitive: false,
      depends_on: null,
      needs_review: null,
      placements: [placement(1, 100)],
      ...extra,
    });
    const FIELDS = {
      ...NO_FIELDS,
      roles: [
        { id: "party-client", slug: "client", label: "Client", kind: "signer", kind_label: null, position: 1, field_count: 3 },
        { id: "party-firm", slug: "firm", label: "Firm", kind: "countersigner", kind_label: null, position: 2, field_count: 1 },
      ],
      fields: [
        field("agreement.term", "Term", {
          holds: "choice",
          placements: [
            placement(1, 200, { kind: "radio", option_value: "Choice1", option_text: "Expires … from Effective Date." }),
            placement(1, 230, { kind: "radio", option_value: "Choice2", option_text: "Continues until terminated." }),
          ],
        }),
        field("agreement.term_years", "Term in years", { depends_on: { key: "agreement.term", option: "Choice1" } }),
        field("client.signature", "Client signature", { holds: "signature", filled_by: "role", role: "client" }),
        field("client.initials", "Client initials", {
          holds: "initials",
          filled_by: "role",
          role: "client",
          placements: [placement(1, 700), placement(2, 700), placement(2, 720)],
        }),
        field("client.tax_id", "Client tax number", { filled_by: "role", role: "client", sensitive: true, needs_review: "not assigned to anyone" }),
        field("firm.signature", "Firm signature", { holds: "signature", filled_by: "role", role: "firm" }),
      ],
    };
    // Read-only views: an approved version shows its fields without the editor.
    const APPROVED = documentWith([approvedVersion(2, { is_current: true }), version(1)]);
    const APPROVED_FIELDS = { ...FIELDS, status: "approved" };
    const scrolled = vi.fn();
    beforeEach(() => {
      scrolled.mockReset();
      Element.prototype.scrollTo = vi.fn() as unknown as Element["scrollTo"];
      Element.prototype.scrollIntoView = scrolled as unknown as Element["scrollIntoView"];
    });
    /** The fields list's rows, as their text (each is a row that opens in place). */
    const rows = (list: HTMLElement) => [...list.children].map((row) => row.querySelector("button")?.textContent ?? "");
    const row = (list: HTMLElement, label: string) => within(list).getByText(label).closest("button") as HTMLButtonElement;

    it("lists every field beside the PDF in sections: who signs, then the fields, needs a look first, choices as a tree", async () => {
      serve(APPROVED, {}, APPROVED_FIELDS);
      open();

      const list = await screen.findByRole("list", { name: "Fields" });
      expect(screen.getByRole("region", { name: "Fields · 6" })).toBeTruthy();
      const parties = screen.getByRole("list", { name: "Who signs" });
      expect(within(parties).getByText("Countersigner")).toBeTruthy();
      expect(within(parties).getByText("Filled in before sending")).toBeTruthy();
      expect(within(parties).queryByRole("button", { name: /^Edit/ })).toBeNull(); // approved: nothing to edit
      const texts = rows(list);
      expect(texts[0]).toContain("Client tax number"); // needs a look: first
      const term = texts.findIndex((text) => text.startsWith("Term") && !text.startsWith("Term in"));
      expect(texts[term + 1]).toContain("Term in years"); // under its choice
    });

    it("opens a field's row in place, says what it is and brings its box into view; steps through its places", async () => {
      serve(APPROVED, {}, APPROVED_FIELDS);
      open();
      const user = userEvent.setup();
      const list = await screen.findByRole("list", { name: "Fields" });

      await user.click(row(list, "Term in years"));
      expect(row(list, "Term in years").getAttribute("aria-expanded")).toBe("true");
      const about = screen.getByRole("region", { name: "Details of Term in years" });
      expect(within(about).getByText("Only when “Expires … from Effective Date.” is chosen")).toBeTruthy();
      expect(scrolled).toHaveBeenCalled();

      await user.click(row(list, "Client initials"));
      expect(screen.queryByRole("region", { name: "Details of Term in years" })).toBeNull(); // one open at a time
      const places = screen.getByRole("group", { name: "Places" });
      expect(within(places).getAllByRole("button").map((chip) => chip.textContent)).toEqual(["1 · Page 1", "2 · Page 2", "3 · Page 2"]);
      expect(within(places).getByRole("button", { name: "Place 1, page 1" }).getAttribute("aria-pressed")).toBe("true");
      const marked = () => [...document.querySelectorAll('button[title="Client initials"]')].map((box) => box.classList.contains("chosen"));
      expect(marked()).toEqual([true, false, false]);
      await user.click(within(places).getByRole("button", { name: "Place 2, page 2" }));
      expect(within(places).getByRole("button", { name: "Place 2, page 2" }).getAttribute("aria-pressed")).toBe("true");
      expect(marked()).toEqual([false, true, false]); // review fix: every place was marked, so the step showed nothing

      await user.click(row(list, "Client initials")); // again: it closes
      expect(screen.queryByRole("region", { name: "Details of Client initials" })).toBeNull();

      await user.click(row(list, "Client tax number"));
      expect(screen.getByText("Private to Client: shown to nobody else")).toBeTruthy();
      expect(screen.getByText("Not assigned to anyone.")).toBeTruthy(); // why it needs a look
      expect(screen.queryByRole("button", { name: "Looks right" })).toBeNull(); // only while editing
    });

    it("opens a field from its box on the PDF, and filters and finds in the list", async () => {
      serve(APPROVED, {}, APPROVED_FIELDS);
      open();
      const user = userEvent.setup();
      const list = await screen.findByRole("list", { name: "Fields" });

      await user.click(document.querySelector('button[title="Firm signature"]') as HTMLButtonElement);
      expect(screen.getByRole("region", { name: "Details of Firm signature" })).toBeTruthy();
      expect(scrolled).toHaveBeenCalledWith({ block: "nearest", behavior: "smooth" }); // its row, smoothly

      const chips = screen.getByRole("group", { name: "Show fields of" });
      await user.click(within(chips).getByRole("button", { name: "Client" }));
      expect(rows(list)).toHaveLength(3);
      await user.click(within(chips).getByRole("button", { name: "All" }));
      await user.type(screen.getByLabelText("Find a field"), "signature");
      expect(rows(list).map((text) => text.slice(0, 16))).toEqual(["Client signature", "Firm signatureFi"]);
    });

    it("draws the places found while the AI says who fills them, with its progress", async () => {
      const detecting = documentWith([version(1, { status: "detecting", is_current: false, field_count: null })], {
        current_version: null,
        latest_version: { id: "v-1", number: 1, status: "detecting", created_at: new Date().toISOString(), field_count: null },
      });
      serve(detecting, {}, {
        ...NO_FIELDS,
        status: "detecting",
        stage: "ai",
        pending: [
          { id: "f1", label: "Print Name", kind: "text", placements: [placement(1, 100)] },
          { id: "f2", label: null, kind: "blank", placements: [placement(2, 300)] },
        ],
      });
      open();

      const steps = await screen.findByRole("list", { name: "Finding fields" });
      expect(within(steps).getByText("Read the document: 2 places to fill")).toBeTruthy();
      expect(within(steps).getByText("Finding who fills each field")).toBeTruthy();
      expect(screen.getAllByText("Finding who fills this…")).toHaveLength(2);
      expect(document.querySelector('button[title="Print Name"]')).toBeTruthy(); // drawn already
      expect(screen.getByRole("region", { name: "Engagement letter, version 1" })).toBeTruthy();
    });

    it("says when nothing was found, and lists what to check before approving", async () => {
      serve(READY, {}, {
        ...NO_FIELDS,
        flags: { ...NO_FIELDS.flags, no_fields: true, addressed_to_ai: true },
        warnings: [
          { code: "no_signer", message: "No party signs this version" },
          { code: "addressed_to_ai", message: "This document contains text addressed to an AI: check its fields with care" },
        ],
      });
      open();
      expect(await screen.findByText("We couldn't find places to fill or sign. Add them below.")).toBeTruthy();
      const check = screen.getByRole("list", { name: "Things to check" });
      expect(within(check).getByText("No party signs this version")).toBeTruthy();
      expect(within(screen.getByRole("region", { name: "Review" })).getByText("2 things to check")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Add field" })).toBeTruthy(); // the list's first row
    });

    it("says when finding the fields again failed, and shows the fields found before", async () => {
      serve(READY, {}, { ...FIELDS, found_again_failed: "Field detection couldn't reach the AI" });
      open();
      expect(await screen.findByText("Field detection couldn't reach the AI. These are the fields found before.")).toBeTruthy();
      expect(rows(screen.getByRole("list", { name: "Fields" })).length).toBeGreaterThan(1);
    });

    it("finds fields again only after confirming, and shows each version's field count", async () => {
      const counted = documentWith([version(2, { is_current: true, field_count: 6 }), version(1, { field_count: 1 })]);
      serve(counted, { "/detection": () => reply(202, { mode: "restart" }) }, FIELDS);
      open();
      const user = userEvent.setup();
      const versions = await screen.findByRole("list", { name: "Versions" });
      expect(within(versions).getByText(/6 fields/)).toBeTruthy();
      expect(within(versions).getByText(/1 field$/)).toBeTruthy();

      await user.click(within(versions).getAllByRole("button", { name: "Find fields again" })[0] as HTMLElement);
      expect(posts("/detection")).toHaveLength(0);
      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText("The fields found now will replace the current ones.")).toBeTruthy();
      await user.click(within(dialog).getByRole("button", { name: "Find fields again" }));
      await vi.waitFor(() => expect(posts("/v-2/detection")).toHaveLength(1));
    });
  });
});
