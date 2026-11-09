import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import { DocumentPage } from "../DocumentPage";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("pdfjs-dist", () => ({
  version: "6.4.299",
  GlobalWorkerOptions: {},
  getDocument: () => ({ promise: new Promise(() => {}), destroy: vi.fn() }),
}));

const META = { version: "1", commit: "x", password_min_length: 12, password_rule: "x", document_max_bytes: 1, document_max_pages: 200 };
const A4 = { width: 595, height: 842, rotation: 0 };
const APPROVAL = { by: { id: "u", name: "Rosa Hale" }, at: "2026-11-08T10:00:00Z" };

const version = (number: number, overrides: Record<string, unknown> = {}) => ({
  id: `v-${number}`,
  number,
  status: "ready",
  problem: null,
  kind: "pdf",
  filename: "Letter.pdf",
  bytes: 2048,
  page_count: 2,
  pages: [A4, A4],
  pages_without_text: [],
  ai_instructions: "",
  uploaded_by: { id: "u", name: "Rosa Hale" },
  created_at: "2026-11-07T10:00:00Z",
  processed_at: "2026-11-07T10:00:05Z",
  field_count: 2,
  name: null,
  description: null,
  derived_from: null,
  approved: null,
  is_current: false,
  ...overrides,
});

const documentWith = (versions: unknown[], overrides: Record<string, unknown> = {}) => ({
  id: "doc-1",
  name: "Engagement letter",
  description: "",
  kind: "pdf",
  page_count: 2,
  current_version: null,
  latest_version: { id: "v-1", number: 1, status: "ready", created_at: "2026-11-07T10:00:00Z", field_count: 2 },
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

const TEXTUAL = ["signature", "initials", "date_signed", "full_name", "company", "email", "tax_id", "text", "note", "other"];
const fieldsView = (overrides: Record<string, unknown> = {}) => ({
  status: "ready",
  stage: "done",
  fields_from: "form_fields",
  pending: [],
  flags: { no_fields: false, addressed_to_ai: false, xfa: false, already_signed: false, repaired: false },
  revision: 0,
  allowed: { text: TEXTUAL, blank: [...TEXTUAL, "checkbox", "choice"], signature: ["signature", "initials"], checkbox: ["checkbox"], radio: ["choice"], combobox: ["choice"], listbox: ["choice"] },
  warnings: [{ code: "needs_a_look", message: "1 field needs a look; approving accepts them as found", count: 1 }],
  roles: [{ id: "party-client", slug: "client", label: "Client", kind: "signer", kind_label: null, position: 1, field_count: 1 }],
  fields: [
    {
      id: "f-sign",
      key: "client.signature",
      label: "Client signature",
      holds: "signature",
      holds_label: null,
      filled_by: "role",
      role: "client",
      party_id: "party-client",
      origin: "detected",
      required: true,
      sensitive: false,
      depends_on: null,
      needs_review: null,
      placements: [{ id: "p-sign", page: 2, rect: [100, 700, 280, 736], kind: "signature", option_value: null, option_text: null }],
    },
    {
      id: "f-company",
      key: "agreement.company",
      label: "Company",
      holds: "company",
      holds_label: null,
      filled_by: "sender",
      role: null,
      party_id: null,
      origin: "detected",
      required: true,
      sensitive: false,
      depends_on: null,
      needs_review: "not sure who fills it",
      placements: [{ id: "p-company", page: 1, rect: [100, 100, 260, 120], kind: "text", option_value: null, option_text: null }],
    },
  ],
  ...overrides,
});

function reply(status: number, body: unknown) {
  return Promise.resolve(
    new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
}

type Sent = { method: string; path: string; body: unknown; key: string | null };

describe("field review", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const sent: Sent[] = [];
  let state: { document: unknown; fields: Record<string, unknown> };
  let answers: Record<string, (body: unknown) => Promise<Response>> = {};

  beforeEach(() => {
    sent.length = 0;
    answers = {};
    push.mockReset();
    Element.prototype.scrollTo = vi.fn() as unknown as Element["scrollTo"]; // jsdom has none
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (input) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      const body = request.method === "GET" ? undefined : await request.clone().json().catch(() => undefined);
      sent.push({ method: request.method, path, body, key: request.headers.get("Idempotency-Key") });
      if (path.endsWith("/meta")) return reply(200, META);
      const answer = Object.entries(answers).find(([route]) => `${request.method} ${path}`.endsWith(route));
      if (answer) return answer[1](body);
      if (path.endsWith("/fields")) {
        const versionId = path.split("/").at(-2) ?? "";
        return reply(200, state.fields[versionId]);
      }
      return reply(200, state.document);
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  const open = () =>
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <ToastProvider>
          <DocumentPage departmentId="d-1" documentId="doc-1" />
        </ToastProvider>
      </QueryClientProvider>,
    );
  const sentTo = (route: string) => sent.filter((r) => `${r.method} ${r.path}`.endsWith(route));
  const inReview = () => {
    state = { document: documentWith([version(1)]), fields: { "v-1": fieldsView() } };
  };
  const chooseField = async (label: string) => {
    const list = await screen.findByRole("list", { name: "Fields" });
    await userEvent.click(within(list).getByRole("button", { name: label }));
  };
  const bar = () => screen.getByRole("region", { name: "Review" });

  it("edits a field, saves it in place, and approves only what is saved", async () => {
    inReview();
    answers["PUT /api/v1/documents/doc-1/versions/v-1/fields"] = () => {
      state.fields["v-1"] = { ...fieldsView({ revision: 1, warnings: [] }), fields: [] };
      return reply(200, { revision: 1 });
    };
    open();
    const user = userEvent.setup();
    await chooseField("Company");
    const form = screen.getByRole("region", { name: "Details of Company" });
    expect(within(form).getByText("Needs a look: not sure who fills it. Any change clears this.")).toBeTruthy();

    const label = within(form).getByLabelText("Label");
    await user.clear(label);
    await user.type(label, "Company name");
    expect(within(bar()).getByText("1 unsaved change")).toBeTruthy(); // typing is one change
    expect(within(bar()).queryByRole("button", { name: "Approve version" })).toBeNull(); // saved first

    await user.click(within(bar()).getByRole("button", { name: "Save" }));
    const [saved] = sentTo("PUT /api/v1/documents/doc-1/versions/v-1/fields");
    expect(saved?.body).toMatchObject({
      revision: 0,
      parties: [{ id: "party-client", label: "Client", kind: "signer" }],
      fields: [
        { id: "f-sign", party_id: "party-client", places: [{ id: "p-sign", kind: "signature" }] },
        { id: "f-company", label: "Company name", filled_by: "sender", party_id: null },
      ],
    });
    // Reloaded at revision 1 with nothing to check: Approve is open.
    await waitFor(() => expect(screen.queryByText(/unsaved change/)).toBeNull());
    expect(within(bar()).getByRole("button", { name: "Approve version" })).toBeTruthy();
  });

  it("undoes and discards unsaved changes", async () => {
    inReview();
    open();
    const user = userEvent.setup();
    await chooseField("Company");
    await user.click(screen.getByLabelText("Required"));
    expect(screen.getByText("1 unsaved change")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.queryByText(/unsaved change/)).toBeNull();
    expect((screen.getByLabelText("Required") as HTMLInputElement).checked).toBe(true);

    await user.click(screen.getByLabelText("Required"));
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.queryByText(/unsaved change/)).toBeNull();
  });

  it("refuses a stale save and offers to reload; names the field a save was refused for", async () => {
    inReview();
    let refuse: "stale" | "invalid" = "stale";
    answers["PUT /api/v1/documents/doc-1/versions/v-1/fields"] = () =>
      refuse === "stale"
        ? reply(409, { type: "x", title: "Someone else saved these fields since you opened them. Reload to see their changes", status: 409, code: "fields-changed" })
        : reply(422, {
            type: "x",
            title: "Validation failed",
            status: 422,
            code: "validation-failed",
            errors: [{ field: "fields[1].places[0].rect", message: "The box must stay on its page" }],
          });
    open();
    const user = userEvent.setup();
    await chooseField("Company");
    await user.click(screen.getByLabelText("Required"));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Reloading shows their changes; yours will be lost.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();

    refuse = "invalid";
    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.click(await screen.findByRole("button", { name: "Company: The box must stay on its page" }));
    expect(screen.getByRole("region", { name: "Details of Company" })).toBeTruthy();
  });

  it("approves after listing the things to check, with the revision and the warnings seen", async () => {
    inReview();
    answers["POST /api/v1/documents/doc-1/versions/v-1/approve"] = () => {
      state.document = documentWith([version(1, { status: "approved", approved: APPROVAL, is_current: true })], {
        current_version: { id: "v-1", number: 1 },
      });
      state.fields["v-1"] = fieldsView({ status: "approved", warnings: [] });
      return reply(204, null);
    };
    open();
    const user = userEvent.setup();
    const check = await screen.findByRole("list", { name: "Things to check" });
    expect(within(check).getByText("1 field needs a look; approving accepts them as found")).toBeTruthy();
    for (const section of ["Things to check", "Who signs", "Fields · 2", "Versions"]) {
      expect(screen.getByRole("button", { name: `About ${section}` })).toBeTruthy(); // each section explains itself
    }
    expect(within(bar()).getByText("1 thing to check")).toBeTruthy();
    expect(within(bar()).getByText("Needs approval")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Approve version" }));
    const dialog = screen.getByRole("dialog", { name: "Approve version 1?" });
    expect(within(dialog).getByText("1 field needs a look; approving accepts them as found")).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "Approve anyway" }));

    expect(sentTo("POST /api/v1/documents/doc-1/versions/v-1/approve")[0]?.body).toEqual({ revision: 0, accepted: ["needs_a_look"] });
    await waitFor(() => expect(within(bar()).getByText(/^Approved by Rosa Hale on /)).toBeTruthy());
    expect(within(bar()).getByRole("button", { name: "Edit fields" })).toBeTruthy();
  });

  it("edits an approved version into the next version, sent once", async () => {
    state = {
      document: documentWith([version(1, { status: "approved", approved: APPROVAL, is_current: true })], {
        current_version: { id: "v-1", number: 1 },
      }),
      fields: { "v-1": fieldsView({ status: "approved", warnings: [] }) },
    };
    answers["POST /api/v1/documents/doc-1/versions/v-1/revisions"] = () => {
      state.document = documentWith(
        [
          version(2, { derived_from: 1, name: "Engagement letter - 2" }),
          version(1, { status: "approved", approved: APPROVAL, is_current: true }),
        ],
        { current_version: { id: "v-1", number: 1 } },
      );
      state.fields["v-2"] = fieldsView({ revision: 1 });
      return reply(201, { version_id: "v-2", number: 2, revision: 1 });
    };
    open();
    const user = userEvent.setup();
    await chooseField("Company");
    expect(screen.queryByLabelText("Label")).toBeNull(); // frozen until Edit fields: details as text
    await user.click(within(bar()).getByRole("button", { name: "Edit fields" }));
    expect(within(bar()).getByText("Saving makes version 2; version 1 stays as it is")).toBeTruthy();
    expect(screen.getByLabelText("Label")).toBeTruthy(); // the open field, now editable
    await user.click(screen.getByLabelText("Required"));
    await user.click(within(bar()).getByRole("button", { name: "Save as version 2" }));

    const [revised] = sentTo("POST /api/v1/documents/doc-1/versions/v-1/revisions");
    expect(revised?.key).toBeTruthy();
    expect(revised?.body).toMatchObject({ revision: 0, fields: [{ id: "f-sign" }, { id: "f-company", required: false }] });
    await waitFor(() => expect(within(bar()).getByText("Version 2")).toBeTruthy()); // the new version opens
    expect(screen.getByText(/from version 1/)).toBeTruthy();
  });

  it("adds a party, and removing one gives its fields to another", async () => {
    inReview();
    open();
    const user = userEvent.setup();
    await screen.findByRole("list", { name: "Fields" });
    await user.click(screen.getByRole("button", { name: "+ Add party" }));
    const form = screen.getByRole("form", { name: "New party" });
    await user.type(within(form).getByLabelText("Name"), "Guarantor");
    await user.click(within(form).getByRole("button", { name: "Add party" }));
    const parties = screen.getByRole("list", { name: "Who signs" });
    expect(within(parties).getByText("Guarantor")).toBeTruthy();

    await user.click(within(parties).getByRole("button", { name: "Edit Client" }));
    expect(within(parties).getByLabelText("Name")).toHaveProperty("value", "Client");
    await user.click(within(parties).getByRole("button", { name: "Remove" }));
    const dialog = screen.getByRole("dialog", { name: "Remove Client?" });
    expect(within(dialog).getByText("What happens to their 1 field?")).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "Remove party" }));
    expect(within(parties).queryByText("Client")).toBeNull();

    await user.click(within(bar()).getByRole("button", { name: "Save" }));
    const body = sentTo("PUT /api/v1/documents/doc-1/versions/v-1/fields")[0]?.body as {
      parties: { id: string; label: string }[];
      fields: { party_id: string | null }[];
    };
    expect(body.parties.map((p) => p.label)).toEqual(["Guarantor"]);
    expect(body.fields[0]?.party_id).toBe(body.parties[0]?.id);
  });

  it("places a new field from the palette and moves it with the keys", async () => {
    inReview();
    open();
    const user = userEvent.setup();
    await screen.findByRole("list", { name: "Fields" });
    await user.click(screen.getByRole("button", { name: "Add field" })); // the list's first row
    const row = screen.getByRole("region", { name: "New field" });
    expect(within(row).getByRole("combobox", { name: "Type" }).textContent).toContain("Signature · Signing"); // one dropdown
    await user.click(within(row).getByRole("button", { name: "Place on the page" }));
    // Pinned over the pages, where the click goes; the row points there.
    expect(screen.getByRole("status")).toHaveTextContent("Click where the signature goes, or drag to draw it");
    expect(within(row).getByText("Click on the document to place it.")).toBeTruthy();

    const layer = document.querySelector('[data-page="1"] [data-layer="fields"]') as HTMLElement;
    fireEvent.pointerDown(layer, { button: 0, pointerId: 1, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(layer, { button: 0, pointerId: 1, clientX: 0, clientY: 0 });

    const form = await screen.findByRole("region", { name: "Details of Signature" });
    expect(within(form).getByRole("button", { name: "Add a place" })).toBeTruthy(); // clear actions, with icons
    expect(within(form).getByRole("button", { name: "On every page" })).toBeTruthy();
    expect(within(form).getByText("Position and size · page 1")).toBeTruthy(); // folded away
    await user.click(within(form).getByRole("button", { name: "About places" }));
    expect(within(form).getByRole("note").textContent).toContain("Add a place: click on the document to show this field there too.");
    await user.keyboard("{Escape}");
    expect((within(form).getByLabelText("Width") as HTMLInputElement).value).toBe("180"); // the default size
    const left = Number((within(form).getByLabelText("Left") as HTMLInputElement).value);
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard("{Shift>}{ArrowRight}{/Shift}{ArrowRight}");
    expect(Number((within(form).getByLabelText("Left") as HTMLInputElement).value)).toBe(left + 11);
    expect(screen.getByText("2 unsaved changes")).toBeTruthy(); // the new field, then one nudge step

    await user.keyboard("{Delete}");
    const ask = screen.getByRole("dialog", { name: "Delete Signature?" });
    await user.click(within(ask).getByRole("button", { name: "Delete field" }));
    expect(screen.queryByRole("region", { name: "Details of Signature" })).toBeNull();
  });

  it("a party with no place to sign gets one from its warning", async () => {
    inReview();
    state.fields["v-1"] = fieldsView({
      warnings: [{ code: "party_cannot_sign", message: "Client has no place to sign", party_id: "party-client" }],
    });
    open();
    const user = userEvent.setup();
    const check = await screen.findByRole("list", { name: "Things to check" });
    await user.click(within(check).getByRole("button", { name: "Add signature" }));
    expect(screen.getByRole("status")).toHaveTextContent("Click where the signature goes, or drag to draw it");

    const layer = document.querySelector('[data-page="2"] [data-layer="fields"]') as HTMLElement;
    fireEvent.pointerDown(layer, { button: 0, pointerId: 1, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(layer, { button: 0, pointerId: 1, clientX: 0, clientY: 0 });

    const form = await screen.findByRole("region", { name: "Details of Client signature" });
    expect(within(form).getByRole("combobox", { name: "Who fills it" }).textContent).toContain("Client"); // the party named
  });

  it("asks before leaving with unsaved changes", async () => {
    inReview();
    open();
    const user = userEvent.setup();
    await chooseField("Company");
    await user.click(screen.getByLabelText("Required"));
    await user.click(screen.getByRole("link", { name: /Documents/ }));

    const dialog = screen.getByRole("dialog", { name: "Discard 1 unsaved change?" });
    expect(push).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Discard" }));
    expect(push).toHaveBeenCalledWith("/departments/d-1/documents");
  });

  it("asks before opening another version with unsaved changes", async () => {
    state = {
      document: documentWith([version(2), version(1, { status: "approved", approved: APPROVAL, is_current: true })], {
        current_version: { id: "v-1", number: 1 },
      }),
      fields: { "v-1": fieldsView({ status: "approved", warnings: [] }), "v-2": fieldsView() },
    };
    open();
    const user = userEvent.setup();
    await within(await screen.findByRole("region", { name: "Review" })).findByText("Version 1");
    await user.click(screen.getByRole("button", { name: "Open" }));
    await waitFor(() => expect(within(bar()).getByText("Version 2")).toBeTruthy());
    await chooseField("Company");
    await user.click(screen.getByLabelText("Required"));
    await user.click(screen.getByRole("button", { name: "Back to the current version" }));

    const dialog = screen.getByRole("dialog", { name: "Discard 1 unsaved change?" });
    await user.click(within(dialog).getByRole("button", { name: "Keep editing" }));
    expect(within(bar()).getByText("Version 2")).toBeTruthy();
  });

  it("gives read-only members the fields without any way to change them", async () => {
    inReview();
    state.document = documentWith([version(1)], { access: "read" });
    open();
    await chooseField("Company");
    expect(screen.getByRole("region", { name: "Details of Company" })).toBeTruthy();
    expect(screen.queryByLabelText("Label")).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve version" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add field" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Add party" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit Client" })).toBeNull();
  });
});
