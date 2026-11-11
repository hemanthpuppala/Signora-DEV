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
  signatures: [],
};

const ADOPTED = { kind: "signature", method: "drawn", text: null, font: null, strokes: [[[100, 200], [600, 250]]], signature_id: "0123456789abcdef" };

const STATE = {
  recipient_id: RECIPIENT,
  kind: "signer" as const,
  name: "Maya Chen",
  email_masked: "m•••@example.com",
  title: "Mutual NDA · Maya Chen",
  document_name: "Mutual NDA",
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
      if (path.endsWith("/signature") && request.method === "GET") return reply(200, { adopted: adopted ? [ADOPTED] : [], saved: [], fonts: [] });
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

    expect(await screen.findByText("1 of 4 done")).toBeTruthy(); // their name was given before sending
    expect(screen.getByText("2 fields left")).toBeTruthy(); // under Sign and submit
    expect(screen.getByRole("button", { name: /Client title/ })).toBeTruthy(); // the panel's list of fields
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

describe("Sign and submit", () => {
  it("submits only once every draft is on the server, the one still being typed included", async () => {
    const requests: string[] = [];
    const held: (() => void)[] = []; // draft saves answered only when the test lets them
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const request = input as Request;
        const path = new URL(request.url).pathname;
        requests.push(`${request.method} ${path}`);
        if (path.endsWith("/document")) return reply(200, DOCUMENT);
        if (path.endsWith("/signature") && request.method === "GET") return reply(200, { adopted: [ADOPTED], saved: [], fonts: [] });
        if (path.includes("/drafts/")) {
          const { value } = (await request.json()) as { value: string };
          await new Promise<void>((resolve) => held.push(resolve));
          requests.push(`saved ${path}`);
          return reply(200, { value });
        }
        if (path.endsWith("/submit")) return reply(200, { signed_at: "2026-11-11T09:14:22Z", next: "done" });
        return reply(204, null);
      }),
    );
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <SigningScreen state={STATE} />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Client signature: sign here" })); // adopted: one tap
    await user.type(await screen.findByLabelText("Client title (required)"), "Founder");
    await user.click(screen.getByRole("button", { name: "Complete" }));
    await user.click(screen.getByLabelText("I've reviewed this document and this is my signature"));

    await user.click(screen.getByRole("button", { name: "Sign and submit" })); // before typing's 0.8 s pause

    await vi.waitFor(() => expect(requests).toContain(`PUT /api/v1/sign/${RECIPIENT}/drafts/title`)); // saved now
    expect(requests).not.toContain(`POST /api/v1/sign/${RECIPIENT}/submit`); // not while saves are on their way
    expect((screen.getByRole("button", { name: "Signing…" }) as HTMLButtonElement).disabled).toBe(true);
    for (const release of held.splice(0)) release();
    await vi.waitFor(() => expect(requests).toContain(`POST /api/v1/sign/${RECIPIENT}/submit`));
    const submitted = requests.indexOf(`POST /api/v1/sign/${RECIPIENT}/submit`);
    expect(requests.indexOf(`saved /api/v1/sign/${RECIPIENT}/drafts/title`)).toBeLessThan(submitted);
    expect(requests.indexOf(`saved /api/v1/sign/${RECIPIENT}/drafts/sig`)).toBeLessThan(submitted);
    vi.unstubAllGlobals();
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
      if (path.endsWith("/signature") && request.method === "GET") return reply(200, { adopted: adoptedOnce ? [ADOPTED] : [], saved: [], fonts: [] });
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

describe("declining", () => {
  it("asks first, asks why, and then says nothing more is needed", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const request = input as Request;
        const path = new URL(request.url).pathname;
        if (path.endsWith("/document")) return reply(200, DOCUMENT);
        if (path.endsWith("/signature")) return reply(200, { adopted: [], saved: [], fonts: [] });
        if (path.endsWith("/decline")) {
          sent.push(await request.json());
          return reply(200, { declined: true });
        }
        return reply(204, null);
      }),
    );
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <SigningScreen state={STATE} />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Decline" }));
    expect(screen.getByText("Declining stops this request for everyone. Hale & Ward LLP will see your reason.")).toBeTruthy();
    const confirm = screen.getByRole("button", { name: "Decline to sign" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true); // a reason first
    await user.type(screen.getByLabelText("Reason"), "The fee is wrong");
    await user.click(confirm);

    expect(await screen.findByText("You declined to sign.")).toBeTruthy();
    expect(sent).toEqual([{ reason: "The fee is wrong" }]);
    vi.unstubAllGlobals();
  });
});

describe("on a small screen", () => {
  it("leads with one button: a dialog per field, Save and next, then signing", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const request = input as Request;
        const path = new URL(request.url).pathname;
        if (path.endsWith("/document")) return reply(200, DOCUMENT);
        if (path.endsWith("/signature")) return reply(200, { adopted: [], saved: [], fonts: [] });
        if (path.includes("/drafts/")) return reply(200, { value: ((await request.json()) as { value: string }).value });
        return reply(204, null);
      }),
    );
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <SigningScreen state={STATE} />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();

    expect(await screen.findByText("Mutual NDA")).toBeTruthy(); // the template's name, not the title
    expect(screen.queryByText("Mutual NDA · Maya Chen")).toBeNull();
    await user.click(screen.getByRole("button", { name: "More" })); // ⋯ holds the rest
    expect(screen.getByRole("menuitem", { name: "Finish later" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Decline" })).toBeTruthy();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Start" }));
    const dialog = await screen.findByRole("dialog", { name: "Client title" });
    expect(within(dialog).getByText("Field 1 of 2")).toBeTruthy();
    await user.type(within(dialog).getByLabelText(/Client title/), "Founder");
    await user.click(within(dialog).getByRole("button", { name: "Save and next" }));

    expect(await screen.findByRole("dialog", { name: "Your signature" })).toBeTruthy(); // the next: sign
    vi.unstubAllGlobals();
  });
});

describe("what others signed", () => {
  it("draws an earlier signature and its signing date where they were signed", async () => {
    const theirs = {
      ...DOCUMENT,
      fields: [
        field("sig-client", "Client signature", { holds: "signature", mine: false, required: false, value: "signature:0123456789abcdef", places: place(60, 500) }),
        field("date-client", "Client signing date", { holds: "date_signed", mine: false, required: false, value: "2026-11-11", format: "Month D, YYYY", places: place(300, 500) }),
      ],
      signatures: [{ kind: "signature", method: "drawn", text: null, font: null, strokes: [[[100, 200], [600, 250]]], signature_id: "0123456789abcdef" }],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const path = new URL((input as Request).url).pathname;
        if (path.endsWith("/document")) return reply(200, theirs);
        if (path.endsWith("/signature")) return reply(200, { adopted: [], saved: [], fonts: [] });
        return reply(204, null);
      }),
    );
    const { container } = render(
      <QueryClientProvider client={makeQueryClient()}>
        <SigningScreen state={{ ...STATE, kind: "countersigner" }} />
      </QueryClientProvider>,
    );

    await vi.waitFor(() => expect(container.querySelector("polyline")).not.toBeNull()); // the client's signature
    expect(container.textContent).toContain("November 11, 2026"); // and the day they signed
    vi.unstubAllGlobals();
  });
});

describe("with nothing to sign or fill", () => {
  it("asks for a review and approval, not a signature", async () => {
    const nothing = { ...DOCUMENT, fields: DOCUMENT.fields.filter((f) => !f.mine) };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const path = new URL((input as Request).url).pathname;
        if (path.endsWith("/document")) return reply(200, nothing);
        if (path.endsWith("/signature")) return reply(200, { adopted: [], saved: [], fonts: [] });
        return reply(204, null);
      }),
    );
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <SigningScreen state={{ ...STATE, kind: "countersigner" }} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("By selecting Approve, I confirm I've reviewed this document and approve it.")).toBeTruthy();
    expect(screen.getByLabelText("I've reviewed this document")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Your fields" })).toBeNull();
    vi.unstubAllGlobals();
  });
});
