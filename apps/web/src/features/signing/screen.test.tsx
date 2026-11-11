import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";

import { SigningScreen } from "./SigningScreen";

vi.mock("pdfjs-dist", () => ({
  version: "6.4.299",
  GlobalWorkerOptions: {},
  getDocument: () => ({ promise: new Promise(() => {}), destroy: vi.fn() }),
}));

const RECIPIENT = "r-1";
const place = (x: number, y: number) => [{ page: 1, rect: [x, y, x + 160, y + 20], option_value: null, text_size: 10 }];
const field = (id: string, label: string, extra: Record<string, unknown> = {}) => ({
  id,
  label,
  holds: "text",
  holds_label: null,
  format: null,
  party_id: "p-client",
  mine: true,
  required: true,
  options: [],
  depends_on: null,
  places: place(60, 100),
  value: null,
  locked: false,
  draft: null,
  hidden: null,
  ...extra,
});

const DOCUMENT = {
  pages: [{ width: 612, height: 792 }],
  parties: [
    { id: "p-client", label: "Client", kind: "signer" },
    { id: "p-firm", label: "Firm", kind: "countersigner" },
  ],
  fields: [
    field("name", "Client printed name", { holds: "full_name", value: "Maya Chen", locked: true, places: place(60, 60) }),
    field("title", "Client title", { places: place(60, 100) }),
    field("phone", "Client phone", { holds: "phone", required: false, places: place(60, 140) }),
    field("sig", "Client signature", { holds: "signature", places: place(60, 500) }),
    field("firm", "Firm signature", { holds: "signature", mine: false, required: false, party_id: "p-firm", hidden: "countersigner", places: place(300, 600) }),
  ],
  font: { id: "liberation-sans", family: "Liberation Sans", url: "/api/v1/fonts/liberation-sans" },
  fit: { min_size: 6, max_size: 12, baseline: 0.25, padding: 2 },
};

const ADOPTED = { kind: "signature", method: "drawn", text: null, font: null, strokes: [[[100, 200], [600, 250]]], signature_id: "0123456789abcdef" };

const STATE = {
  recipient_id: RECIPIENT,
  name: "Maya Chen",
  email_masked: "m•••@example.com",
  title: "Mutual NDA · Maya Chen",
  company: "Hale & Ward LLP",
  sender_name: "Rosa Hale",
  sender_email: "rosa@haleward.example",
  next: "sign" as const,
  signed_at: null,
  disclosure: { version: "esign-disclosure-v1", agreement: "I agree.", paragraphs: [] },
};

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}

describe("the signer's screen", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const requests: string[] = [];
  let adopted = false;
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (input) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      requests.push(`${request.method} ${path}`);
      if (path.endsWith("/document")) return reply(200, DOCUMENT);
      if (path.endsWith("/signature") && request.method === "GET") return reply(200, { adopted: adopted ? [ADOPTED] : [], fonts: [] });
      if (path.endsWith("/signature/signature")) {
        adopted = true;
        return reply(200, ADOPTED);
      }
      if (path.includes("/drafts/")) return reply(200, { value: ((await request.json()) as { value: string }).value });
      if (path.endsWith("/submit")) {
        expect(request.headers.get("Idempotency-Key")).toBeTruthy();
        return reply(200, { signed_at: "2026-11-11T09:14:22Z", next: "done" });
      }
      return reply(204, null);
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    requests.length = 0;
    adopted = false;
  });

  function show() {
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <SigningScreen state={STATE} />
      </QueryClientProvider>,
    );
  }

  it("counts what is left, and holds Sign and submit until it is done and confirmed", async () => {
    show();

    expect(await screen.findAllByText("2 fields left")).toHaveLength(2); // in the bar, and under Submit
    expect(screen.getByRole("button", { name: "Start" })).toBeTruthy();
    const submit = screen.getByRole("button", { name: "Sign and submit" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(screen.getByText(/I agree to sign this document electronically/)).toBeTruthy();
    expect(requests).toContain(`POST /api/v1/sign/${RECIPIENT}/viewed`);
  });

  it("offers to finish later without losing anything", async () => {
    show();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Finish later" }));

    expect(screen.getByText("Your progress is saved.")).toBeTruthy();
  });

  it("types into the field's box on the page, saves it once typing stops, and moves to Complete", async () => {
    show();
    const user = userEvent.setup();
    const box = await screen.findByLabelText("Client title (required)");
    expect(within(document.body).queryByLabelText("Client printed name (required)")).toBeNull(); // locked: drawn

    await user.type(box, "Founder");

    await vi.waitFor(() => expect(requests).toContain(`PUT /api/v1/sign/${RECIPIENT}/drafts/title`), { timeout: 2000 });
    await signThePlace(user);
    expect(screen.getByRole("button", { name: "Complete" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Complete" }));
    await user.click(screen.getByLabelText("I've reviewed this document and this is my signature"));
    const submit = screen.getByRole("button", { name: "Sign and submit" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    await user.click(submit);

    await vi.waitFor(() => expect(requests).toContain(`POST /api/v1/sign/${RECIPIENT}/submit`));
  });
});

async function signThePlace(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Client signature: sign here" }));
  expect(await screen.findByRole("dialog", { name: "Your signature" })).toBeTruthy();
  const pad = screen.getByRole("img", { name: "Draw your signature" });
  pad.getBoundingClientRect = () => ({ left: 0, top: 0, width: 500, height: 200, right: 500, bottom: 200, x: 0, y: 0, toJSON: () => ({}) });
  fireEvent.pointerDown(pad, { clientX: 50, clientY: 100, pointerId: 1 });
  fireEvent.pointerMove(pad, { clientX: 300, clientY: 120, pointerId: 1 });
  fireEvent.pointerUp(pad, { clientX: 300, clientY: 120, pointerId: 1 });
  await user.click(screen.getByRole("button", { name: "Adopt and sign" }));
  await vi.waitFor(() => expect(screen.queryByRole("dialog", { name: "Your signature" })).toBeNull());
}

describe("signing a place", () => {
  it("adopts a drawing the first time, then signs the place with it", async () => {
    const calls: { method: string; path: string; body: unknown }[] = [];
    let adoptedOnce = false;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      const body = request.method === "GET" ? null : await request.text().then((t) => (t ? JSON.parse(t) : null));
      calls.push({ method: request.method, path, body });
      if (path.endsWith("/document")) return reply(200, DOCUMENT);
      if (path.endsWith("/signature") && request.method === "GET") return reply(200, { adopted: adoptedOnce ? [ADOPTED] : [], fonts: [] });
      if (path.endsWith("/signature/signature")) {
        adoptedOnce = true;
        return reply(200, ADOPTED);
      }
      if (path.includes("/drafts/")) return reply(200, { value: (body as { value: string }).value });
      return reply(204, null);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <SigningScreen state={STATE} />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await screen.findByRole("button", { name: "Client signature: sign here" });

    await signThePlace(user);

    const adopt = calls.find((c) => c.path.endsWith("/signature/signature"));
    expect(adopt?.method).toBe("PUT");
    expect((adopt?.body as { method: string }).method).toBe("drawn");
    expect(((adopt?.body as { strokes: number[][][] }).strokes[0] ?? []).length).toBeGreaterThan(1);
    await vi.waitFor(() => expect(calls.some((c) => c.path.endsWith("/drafts/sig") && (c.body as { value: string }).value === "signed")).toBe(true));
    vi.unstubAllGlobals();
  });
});
