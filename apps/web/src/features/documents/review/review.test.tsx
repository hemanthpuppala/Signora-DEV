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
  formats: {
    date: ["Month D, YYYY", "MM/DD/YYYY", "DD/MM/YYYY", "MM/DD/YY", "DD/MM/YY", "YYYY-MM-DD", "D Month YYYY"],
    day: ["D", "Dth"],
    month: ["Month", "MM"],
    year: ["YYYY", "YY"],
  },
  shared: ["signature", "initials", "date_signed", "party_name"],
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
      format: null,
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
      format: null,
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

  const open = (client = makeQueryClient()) =>
    render(
      <QueryClientProvider client={client}>
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
  // The chosen box on the page: where a place is, read from how it is drawn.
  const chosenBox = () =>
    [...document.querySelectorAll<HTMLElement>('[data-layer="fields"] > button')].find((b) => /chosen/.test(b.className)) as HTMLElement;
  // The version on screen and its state, in the title's line (V2 · Needs approval).
  const shownVersion = () => screen.getByRole("heading", { level: 1 }).parentElement as HTMLElement;

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
    expect(within(form).getByText("Not sure who fills it.")).toBeTruthy();

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

  it("walks the fields that need a look: named in Things to check, Looks right moves on, and the save says so", async () => {
    inReview();
    const base = fieldsView();
    state.fields["v-1"] = {
      ...base,
      fields: base.fields.map((field) => (field.id === "f-sign" ? { ...field, needs_review: "two boxes found" } : field)),
    };
    answers["PUT /api/v1/documents/doc-1/versions/v-1/fields"] = () => reply(200, { revision: 1 });
    open();
    const user = userEvent.setup();
    const check = await screen.findByRole("list", { name: "Things to check" });
    expect(within(check).getByText("Client signature needs a look")).toBeTruthy();
    expect(within(check).getByText("Company needs a look")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Needs a look · 2" })).toBeTruthy(); // the Fields filter
    const who = screen.getByRole("list", { name: "Who signs" });
    expect(within(who).getAllByText("1 to check")).toHaveLength(2); // Client's, and one filled before sending

    const signature = within(check).getByText("Client signature needs a look").closest("li") as HTMLElement;
    await user.click(within(signature).getByRole("button", { name: "Show me" }));
    const form = screen.getByRole("region", { name: "Details of Client signature" });
    expect(within(form).getByText("Two boxes found.")).toBeTruthy();
    expect(within(form).getByRole("button", { name: "Next · 1 of 2" })).toBeTruthy();

    await user.click(within(form).getByRole("button", { name: "Looks right" }));

    const next = screen.getByRole("region", { name: "Details of Company" }); // on to the next one
    expect(within(next).queryByRole("button", { name: /^Next/ })).toBeNull(); // the last one left
    expect(within(check).queryByText("Client signature needs a look")).toBeNull();
    expect(screen.getByRole("button", { name: "Needs a look · 1" })).toBeTruthy();
    await user.click(within(bar()).getByRole("button", { name: "Save" }));
    const [saved] = sentTo("PUT /api/v1/documents/doc-1/versions/v-1/fields");
    expect(saved?.body).toMatchObject({
      fields: [
        { id: "f-sign", checked: true },
        { id: "f-company", checked: false },
      ],
    });
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

  it("keeps unsaved edits when the fields are saved elsewhere, says so, and reloads only when asked", async () => {
    // Optimistic concurrency on this side too: the newer fields replaced the draft unasked, with
    // the unsaved count back at 0 and no word of it.
    inReview();
    const client = makeQueryClient();
    open(client);
    const user = userEvent.setup();
    await chooseField("Company");
    await user.click(screen.getByLabelText("Required"));
    expect(within(bar()).getByText(/1 unsaved change/)).toBeTruthy();

    state.fields["v-1"] = fieldsView({ revision: 1 }); // someone else saved
    await client.invalidateQueries({ queryKey: ["fields", "v-1"] });

    expect(await screen.findByText("Reloading shows their changes; yours will be lost.")).toBeTruthy();
    expect(within(bar()).getByText(/1 unsaved change/)).toBeTruthy(); // the edit is still here
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(sentTo("PUT /api/v1/documents/doc-1/versions/v-1/fields")).toHaveLength(0); // it would be refused

    await user.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(screen.queryByText(/unsaved change/)).toBeNull());
    expect(screen.queryByText("Reloading shows their changes; yours will be lost.")).toBeNull();
  });

  it("takes no edit while a save is on its way, and shows what was saved without a false alarm", async () => {
    inReview();
    let finish: (response: Response) => void = () => {};
    answers["PUT /api/v1/documents/doc-1/versions/v-1/fields"] = () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      });
    open();
    const user = userEvent.setup();
    await chooseField("Company");
    const required = () => screen.getByLabelText<HTMLInputElement>("Required");
    await user.click(required());
    const sentAs = required().checked;
    await user.click(screen.getByRole("button", { name: "Save" }));

    // While the request is in flight the editor says it is busy and takes no input.
    const editor = required().closest("[aria-busy]");
    expect(editor?.getAttribute("aria-busy")).toBe("true");
    expect(editor?.hasAttribute("inert")).toBe(true);
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Undo" }).disabled).toBe(true);
    await user.click(required()); // a test DOM does not honour inert: the draft still does not move
    expect(required().checked).toBe(sentAs);

    state.fields["v-1"] = fieldsView({ revision: 1 });
    finish(new Response(JSON.stringify({ revision: 1 }), { status: 200, headers: { "content-type": "application/json" } }));
    await waitFor(() => expect(screen.queryByText(/unsaved change/)).toBeNull());
    expect(screen.queryByText("Reloading shows their changes; yours will be lost.")).toBeNull();
    expect(required().closest("[aria-busy]")).toBeNull(); // open for input again
  });

  it("keeps a refused save's errors on the fields they were about, whatever is edited next", async () => {
    // The errors name fields by their place in the body that was sent. Read against the draft as
    // it is now, deleting an earlier field moved each one onto the wrong field, or onto none.
    inReview();
    answers["PUT /api/v1/documents/doc-1/versions/v-1/fields"] = () =>
      reply(422, {
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
    expect(await screen.findByRole("button", { name: "Company: The box must stay on its page" })).toBeTruthy();

    await chooseField("Client signature"); // the field before it
    await user.click(screen.getByRole("button", { name: "Delete field" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete field" }));

    expect(screen.getByRole("button", { name: "Company: The box must stay on its page" })).toBeTruthy();
  });

  it("gives each thing to check its own row, two about one field included", async () => {
    // A box over two others is two warnings with one field: they had one React key.
    inReview();
    state.fields["v-1"] = fieldsView({
      warnings: [
        { code: "overlapping_places", message: "Company overlaps Client signature on page 2", field_id: "f-company" },
        { code: "overlapping_places", message: "Company overlaps Date on page 2", field_id: "f-company" },
      ],
    });
    const complaints = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      open();
      const check = await screen.findByRole("list", { name: "Things to check" });
      expect(within(check).getAllByRole("listitem")).toHaveLength(3); // Company's look, then its two overlaps
      expect(complaints.mock.calls.filter((call) => String(call[0]).includes("same key"))).toHaveLength(0);
    } finally {
      complaints.mockRestore();
    }
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
    expect(within(check).getByText("Company needs a look")).toBeTruthy(); // named, with why and Show me
    expect(within(check).getByText("not sure who fills it")).toBeTruthy();
    for (const section of ["Things to check", "Who signs", "Fields · 2", "Versions"]) {
      expect(screen.getByRole("button", { name: `About ${section}` })).toBeTruthy(); // each section explains itself
    }
    expect(within(bar()).getByText("1 thing to check")).toBeTruthy();
    expect(within(screen.getByRole("group", { name: "Version state" })).getByText("Needs approval")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Approve version" }));
    const dialog = screen.getByRole("dialog", { name: "Approve version 1?" });
    expect(within(dialog).getByText("Company still needs a look; approving accepts it as found")).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "Approve anyway" }));

    expect(sentTo("POST /api/v1/documents/doc-1/versions/v-1/approve")[0]?.body).toEqual({ revision: 0, accepted: ["needs_a_look"] });
    // Approved, by whom and when: in the title's line.
    await waitFor(() => expect(within(screen.getByRole("group", { name: "Version state" })).getByText(/^Rosa Hale · /)).toBeTruthy());
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
    await waitFor(() => expect(within(shownVersion()).getByText("V2")).toBeTruthy()); // the new version opens
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
    expect(within(row).getByRole("combobox", { name: "Type" }).textContent).toBe("Signature"); // one dropdown; its group beside each option
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
    // Its place moves and resizes without a drag too: named groups of named icons, no numbers.
    const named = (group: string) =>
      within(within(form).getByRole("group", { name: group }))
        .getAllByRole("button")
        .map((b) => b.getAttribute("aria-label"));
    expect(named("Add places")).toEqual(["Add a place", "On every page"]);
    expect(named("Move this place")).toEqual(["Move left", "Move up", "Move down", "Move right"]);
    expect(named("Resize this place")).toEqual(["Smaller", "Larger"]);
    expect(within(form).queryByRole("group", { name: "Place 1" })).toBeNull(); // one place: nothing to split or remove
    const adjust = form;
    await user.click(within(form).getByRole("button", { name: "About places" }));
    expect(within(form).getByRole("note").textContent).toContain("Add a place: click on the document to show this field there too.");
    await user.keyboard("{Escape}");
    const box = () => chosenBox();
    const scale = parseFloat(box().style.width) / 180; // the default size, in points
    const left = parseFloat(box().style.left) / scale;
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard("{Shift>}{ArrowRight}{/Shift}{ArrowRight}");
    expect(parseFloat(box().style.left) / scale).toBeCloseTo(left + 11);
    expect(screen.getByText("2 unsaved changes")).toBeTruthy(); // the new field, then one nudge step
    await user.click(within(adjust).getByRole("button", { name: "Move right" }));
    expect(parseFloat(box().style.left) / scale).toBeCloseTo(left + 13);
    await user.click(within(adjust).getByRole("button", { name: "Larger" }));
    expect(parseFloat(box().style.width) / scale).toBeCloseTo(198);

    await user.keyboard("{Delete}");
    const ask = screen.getByRole("dialog", { name: "Delete Signature?" });
    await user.click(within(ask).getByRole("button", { name: "Delete field" }));
    expect(screen.queryByRole("region", { name: "Details of Signature" })).toBeNull();
  });

  it("arrow keys in a dropdown pick an option and never move the box", async () => {
    inReview();
    open();
    const user = userEvent.setup();
    await chooseField("Company");
    const form = await screen.findByRole("region", { name: "Details of Company" });
    const left = chosenBox().style.left;
    within(form).getByRole("combobox", { name: "Type" }).focus();
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}"); // opens the list, moves down one, picks it

    expect(chosenBox().style.left).toBe(left);
    expect(screen.getByText("1 unsaved change")).toBeTruthy(); // the type, not a nudge
    await user.keyboard("{Backspace}");
    expect(screen.queryByRole("dialog")).toBeNull(); // the place was not removed
    expect(screen.getByRole("region", { name: "Details of Company" })).toBeTruthy();
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
    await user.click(screen.getByRole("link", { name: /Templates/ }));

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
    await within(await screen.findByRole("region", { name: "Review" })).findByRole("button", { name: "Edit fields" });
    expect(within(shownVersion()).getByText("V1")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await waitFor(() => expect(within(shownVersion()).getByText("V2")).toBeTruthy());
    await chooseField("Company");
    await user.click(screen.getByLabelText("Required"));
    await user.click(screen.getByRole("button", { name: "Back to the current version" }));

    const dialog = screen.getByRole("dialog", { name: "Discard 1 unsaved change?" });
    await user.click(within(dialog).getByRole("button", { name: "Keep editing" }));
    expect(within(shownVersion()).getByText("V2")).toBeTruthy();
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

  describe("with a finger, and on a narrow screen (§5.1)", () => {
    const boxOf = (page: number) => document.querySelector(`[data-page="${page}"] [data-layer="fields"] > button`) as HTMLElement;
    const layerOf = (page: number) => document.querySelector(`[data-page="${page}"] [data-layer="fields"]`) as HTMLElement;
    const at = (x: number, y: number, pointerType = "mouse") => ({ button: 0, pointerId: 1, clientX: x, clientY: y, pointerType });
    /** Two A4 pages on screen at scale 1, a 16px gap between them. */
    const laidOut = () => {
      for (const [page, top] of [[1, 0], [2, 858]] as const) {
        layerOf(page).getBoundingClientRect = () => new DOMRect(0, top, 595, 842);
      }
    };
    /** A screen where a query holds only if it is one of these. */
    const screenIs = (...holding: string[]) =>
      vi.stubGlobal("matchMedia", (media: string) => ({
        media,
        matches: holding.includes(media),
        addEventListener: () => {},
        removeEventListener: () => {},
      }));

    it("a tap places a field at its size, and the words say tap", async () => {
      screenIs("(min-width: 960px)", "(pointer: coarse)");
      inReview();
      open();
      const user = userEvent.setup();
      await screen.findByRole("list", { name: "Fields" });
      await user.click(screen.getByRole("button", { name: "Add field" }));
      const row = screen.getByRole("region", { name: "New field" });
      await user.click(within(row).getByRole("button", { name: "Place on the page" })); // the same on every screen
      expect(screen.getByRole("status")).toHaveTextContent("Tap where the signature goes");
      expect(within(row).getByText("Tap the document to place it.")).toBeTruthy();

      laidOut();
      // A finger is never still: its wobble draws nothing, the box has its type's size.
      fireEvent.pointerDown(layerOf(1), at(300, 400, "touch"));
      fireEvent.pointerMove(layerOf(1), at(306, 405, "touch"));
      fireEvent.pointerUp(layerOf(1), at(306, 405, "touch"));
      await screen.findByRole("region", { name: "Details of Signature" });
      const placed = [...layerOf(1).querySelectorAll<HTMLElement>("button")].find((b) => /chosen/.test(b.className));
      expect([placed?.style.left, placed?.style.top, placed?.style.width, placed?.style.height]).toEqual(["210px", "382px", "180px", "36px"]);
    });

    it("a finger moves the chosen box only: a tap chooses, the next drag moves", async () => {
      inReview();
      open();
      await screen.findByRole("list", { name: "Fields" });
      laidOut();
      const drag = (from: [number, number], to: [number, number]) => {
        fireEvent.pointerDown(boxOf(1), at(...from, "touch"));
        fireEvent.pointerMove(boxOf(1), at(...to, "touch"));
        fireEvent.pointerUp(boxOf(1), at(...to, "touch"));
      };
      drag([150, 110], [190, 150]); // not chosen: this drag is the page's, to scroll
      expect(boxOf(1).style.left).toBe("100px");

      fireEvent.click(boxOf(1));
      await screen.findByRole("region", { name: "Details of Company" });
      drag([150, 110], [154, 113]); // a tap that wandered: no move
      expect(boxOf(1).style.left).toBe("100px");
      drag([150, 110], [190, 150]);
      expect([boxOf(1).style.left, boxOf(1).style.top]).toEqual(["140px", "140px"]);
      expect(screen.getByText("1 unsaved change")).toBeTruthy();
    });

    it("a box dragged past its page lands on the next one", async () => {
      inReview();
      answers["PUT /api/v1/documents/doc-1/versions/v-1/fields"] = () => reply(200, { revision: 1 });
      open();
      const user = userEvent.setup();
      await screen.findByRole("list", { name: "Fields" });
      laidOut();
      fireEvent.pointerDown(boxOf(1), at(150, 110));
      fireEvent.pointerMove(boxOf(1), at(170, 1010)); // over page 2, which starts at 858
      expect(boxOf(1).className).toMatch(/dragged/); // drawn over the next page while on its way
      fireEvent.pointerUp(boxOf(1), at(170, 1010));

      expect(layerOf(1).querySelector("button")).toBeNull();
      const moved = [...layerOf(2).querySelectorAll<HTMLElement>("button")].find((b) => b.title === "Company");
      expect([moved?.style.left, moved?.style.top]).toEqual(["120px", "142px"]); // where it was let go, in page 2's points
      await user.click(within(bar()).getByRole("button", { name: "Save" }));
      const body = sentTo("PUT /api/v1/documents/doc-1/versions/v-1/fields")[0]?.body as {
        fields: { label: string; places: { page: number; rect: number[]; kind: string }[] }[];
      };
      expect(body.fields.find((f) => f.label === "Company")?.places).toMatchObject([{ page: 2, rect: [120, 142, 280, 162], kind: "text" }]);
    });

    it("under the document, a box chosen on the page keeps the person there, with the way to its form", async () => {
      screenIs("(pointer: coarse)"); // narrow: the panel is under the document
      const scrolled = vi.fn();
      Element.prototype.scrollIntoView = scrolled as unknown as Element["scrollIntoView"];
      inReview();
      open();
      await screen.findByRole("list", { name: "Fields" });

      fireEvent.click(boxOf(1));
      await screen.findByRole("region", { name: "Details of Company" });
      expect(scrolled).not.toHaveBeenCalled(); // the list under the document does not pull the page away
      const pinned = screen.getByRole("status");
      expect(pinned).toHaveTextContent("Company");
      await userEvent.click(within(pinned).getByRole("button", { name: "Details" }));
      expect(scrolled.mock.contexts.at(-1)).toBe(document.getElementById("field-f-company")); // its row, on request

      scrolled.mockClear();
      await chooseField("Client signature"); // chosen in the list: the list shows it, nothing is pinned
      expect(scrolled).toHaveBeenCalled();
      expect(screen.queryByRole("status")).toBeNull();
    });

    it("under the document, Edit fields is in the panel's title line, not on a line of its own above", async () => {
      screenIs("(pointer: coarse)");
      state = {
        document: documentWith([version(1, { status: "approved", approved: APPROVAL, is_current: true })], {
          current_version: { id: "v-1", number: 1 },
        }),
        fields: { "v-1": fieldsView({ status: "approved", warnings: [] }) },
      };
      open();
      const user = userEvent.setup();
      const who = await screen.findByRole("region", { name: "Who signs" });
      expect(screen.queryByRole("region", { name: "Review" })).toBeNull(); // no bar for one button
      await user.click(within(who).getByRole("button", { name: "Edit fields" }));
      expect(within(who).getByText("Client")).toBeTruthy(); // pressing it never closes the section
      expect(await screen.findByRole("button", { name: "Add field" })).toBeTruthy(); // editing
      expect(within(who).queryByRole("button", { name: "Edit fields" })).toBeNull();
      expect(within(bar()).getByRole("button", { name: "Stop editing" })).toBeTruthy(); // what stays in reach
    });
  });
});
