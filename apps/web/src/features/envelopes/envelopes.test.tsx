import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import { EnvelopePage } from "./EnvelopePage";
import { EnvelopesList } from "./EnvelopesList";

vi.mock("pdfjs-dist", () => ({
  version: "6.4.299",
  GlobalWorkerOptions: {},
  getDocument: () => ({ promise: new Promise(() => {}), destroy: vi.fn() }),
}));

const summary = (id: string, title: string, overrides: Record<string, unknown> = {}) => ({
  id,
  title,
  status: "sent",
  document_id: "doc-1",
  document_name: "Mutual NDA",
  version_number: 2,
  signers: ["Maya Chen"],
  signed: 0,
  sent_at: "2026-11-09T10:00:00Z",
  expires_at: "2026-11-23T10:00:00Z",
  ...overrides,
});

const recipient = (id: string, overrides: Record<string, unknown> = {}) => ({
  id,
  kind: "signer",
  party_id: "p-client",
  party_label: "Client",
  name: "Maya Chen",
  email: "maya@example.com",
  status: "sent",
  sent_at: "2026-11-09T10:00:00Z",
  opened_at: null,
  viewed_at: null,
  signed_at: null,
  delivery: { status: "sent", error: null },
  ...overrides,
});

const ENVELOPE = {
  id: "env-1",
  title: "Mutual NDA · Maya Chen",
  status: "sent",
  department_id: "d-1",
  document_id: "doc-1",
  document_name: "Mutual NDA",
  version_id: "v-2",
  version_number: 2,
  sent_by: { id: "u", name: "Rosa Hale" },
  sent_at: "2026-11-09T10:00:00Z",
  expires_at: "2026-11-23T10:00:00Z",
  cancelled_at: null,
  require_email_code: true, // the envelope's own setting (Phase 7 §4)
  reminder_interval_hours: 24,
  max_reminders: 5,
  notify_emails: [],
  recipients: [
    recipient("r-maya"),
    recipient("r-ben", { name: "Ben Ode", email: "ben@example.com", delivery: { status: "failed", error: "mailbox full" } }),
    recipient("r-rosa", { kind: "countersigner", party_id: "p-firm", party_label: "Firm", name: "Rosa Hale", email: "rosa@firm.example", status: "waiting", sent_at: null, delivery: null }),
  ],
  values: [{ field_id: "f-date", value: "2026-12-01", given_by: "sender" }],
  timeline: [
    { at: "2026-11-09T10:05:00Z", action: "envelope.resent", by: "rosa@firm.example", data: { recipient_id: "r-ben" } },
    { at: "2026-11-09T10:00:00Z", action: "envelope.sent", by: "rosa@firm.example", data: { signers: 2 } },
  ],
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

describe("envelopes", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const calls: { method: string; path: string; query: string; body: unknown; key: string | null }[] = [];
  let envelope: Record<string, unknown>;

  beforeEach(() => {
    calls.length = 0;
    envelope = structuredClone(ENVELOPE);
    Element.prototype.scrollTo = vi.fn() as unknown as Element["scrollTo"];
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (input) => {
      const request = input as Request;
      const url = new URL(request.url);
      const body = request.method === "GET" ? undefined : await request.clone().json().catch(() => undefined);
      calls.push({ method: request.method, path: url.pathname, query: url.search, body, key: request.headers.get("Idempotency-Key") });
      const route = `${request.method} ${url.pathname}`;
      if (route.endsWith("/departments/d-1/envelopes")) {
        if (url.searchParams.get("cursor")) return reply(200, { envelopes: [summary("env-3", "Oldest")], next_cursor: null });
        if (url.searchParams.get("status") === "completed")
          return reply(200, { envelopes: [summary("env-2", "Done", { status: "completed", signed: 1 })], next_cursor: null });
        return reply(200, { envelopes: [summary("env-1", "Mutual NDA · Maya Chen")], next_cursor: "next" });
      }
      if (route === "GET /api/v1/envelopes/env-1") return reply(200, envelope);
      if (route.endsWith("/send-form")) return reply(404, { type: "x", title: "x", status: 404, code: "not-found" });
      if (route.endsWith("/link")) return reply(200, { url: "https://signora.example/s/abc" });
      if (route.endsWith("/resend")) return reply(200, { recipient_id: "r-ben" });
      if (route.endsWith("/recipients/r-maya/remind")) return reply(200, { reminded: 1 });
      if (route.endsWith("/remind")) return reply(200, { reminded: 2 });
      if (route.endsWith("/cancel")) return reply(200, { ...envelope, status: "cancelled", cancelled_at: "2026-11-10T10:00:00Z" });
      if (request.method === "PATCH") return reply(200, { ...envelope, recipients: [recipient("r-maya", { email: "maya.chen@example.org" })] });
      return reply(404, {});
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });
  const sentTo = (suffix: string) => calls.filter((c) => c.method !== "GET" && c.path.endsWith(suffix));

  it("lists a department's envelopes, filters them and shows more", async () => {
    wrap(<EnvelopesList departmentId="d-1" />);
    const user = userEvent.setup();

    const link = await screen.findByRole("link", { name: "Mutual NDA · Maya Chen" });
    expect(link.getAttribute("href")).toBe("/departments/d-1/envelopes/env-1");
    expect(screen.getByText("0 of 1 signed")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Show more" }));
    expect(await screen.findByRole("link", { name: "Oldest" })).toBeTruthy();

    await user.click(within(screen.getByRole("group", { name: "Show envelopes" })).getByRole("button", { name: "Completed" }));
    expect(await screen.findByRole("link", { name: "Done" })).toBeTruthy();
    expect(calls.some((c) => c.query.includes("status=completed"))).toBe(true);
  });

  it("follows one envelope: copy a link, send again, correct an email, remind, an email not delivered", async () => {
    wrap(<EnvelopePage departmentId="d-1" envelopeId="env-1" />);
    const user = userEvent.setup(); // installs a clipboard: spy on that one
    const writeText = vi.spyOn(navigator.clipboard, "writeText");

    // Grouped: who signs, who countersigns; each person a card with their moments.
    const signers = await screen.findByRole("list", { name: "Signers" });
    const rows = within(signers).getAllByRole("listitem");
    const firm = within(screen.getByRole("list", { name: "Countersigners" })).getByRole("listitem");
    expect(firm.textContent).toContain("Firm · rosa@firm.example");
    expect(firm.textContent).toContain("Emailed once every signer has signed");
    expect(within(firm).queryByRole("button", { name: "Copy link" })).toBeNull(); // not their turn
    expect(rows[0]?.textContent).toContain("Sent Nov 9");
    expect(within(rows[0] as HTMLElement).queryByRole("button", { name: "Send again" })).toBeNull(); // delivered
    expect(screen.getByText("Email not delivered: mailbox full")).toBeTruthy();
    expect(screen.getByText("Emailed Ben Ode again")).toBeTruthy();
    expect(screen.getByText("Sent to 2 signers")).toBeTruthy();
    // The settings sit beside the recipients; the action bar keeps the state and the dates.
    const settings = screen.getAllByLabelText("Settings").find((el) => el.tagName === "DL") as HTMLElement;
    expect(within(settings).getByText("Required to open")).toBeTruthy();

    await user.click(within(rows[0] as HTMLElement).getByRole("button", { name: "Copy link" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("https://signora.example/s/abc"));
    expect(await screen.findByText("Maya Chen's link copied")).toBeTruthy();

    await user.click(within(rows[0] as HTMLElement).getByRole("button", { name: "Remind" }));
    await waitFor(() => expect(sentTo("/recipients/r-maya/remind")).toHaveLength(1));
    expect(await screen.findByText("Reminded Maya Chen")).toBeTruthy();

    await user.click(within(rows[1] as HTMLElement).getByRole("button", { name: "Send again" })); // undelivered: retry
    await waitFor(() => expect(sentTo("/recipients/r-ben/resend")).toHaveLength(1));
    expect(sentTo("/recipients/r-ben/resend")[0]?.key).toBeTruthy();

    await user.click(within(rows[0] as HTMLElement).getByRole("button", { name: "Change Maya Chen's email" }));
    const form = screen.getByRole("form", { name: "Change Maya Chen" });
    const email = within(form).getByLabelText("Email");
    await user.clear(email);
    await user.type(email, "maya.chen@example.org");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sentTo("/recipients/r-maya")[0]?.body).toEqual({ email: "maya.chen@example.org" }));

    await user.click(screen.getByRole("button", { name: "Remind now" }));
    expect(await screen.findByText("Reminded 2 people")).toBeTruthy();
  });

  it("says when the document can't be shown, and offers to ask again, instead of a blank pane", async () => {
    wrap(<EnvelopePage departmentId="d-1" envelopeId="env-1" />);
    expect(await screen.findByText("The document can't be shown")).toBeTruthy();
    const before = calls.filter((c) => c.path.endsWith("/send-form")).length;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(calls.filter((c) => c.path.endsWith("/send-form")).length).toBeGreaterThan(before));
  });

  it("cancels only after confirming", async () => {
    wrap(<EnvelopePage departmentId="d-1" envelopeId="env-1" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Cancel envelope" }));
    const dialog = screen.getByRole("dialog", { name: "Cancel this envelope?" });
    expect(sentTo("/cancel")).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Cancel envelope" }));

    await waitFor(() => expect(sentTo("/cancel")).toHaveLength(1));
    expect((await screen.findAllByText("Withdrawn")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Remind now" })).toBeNull(); // closed
  });
});
