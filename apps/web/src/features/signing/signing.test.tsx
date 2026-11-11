import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";

import { forgetExchangesForTests, OpenLink } from "./OpenLink";
import { SignerPage } from "./SignerPage";

vi.mock("pdfjs-dist", () => ({
  version: "6.4.299",
  GlobalWorkerOptions: {},
  getDocument: () => ({ promise: new Promise(() => {}), destroy: vi.fn() }),
}));

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const RECIPIENT = "0193a5f2-0000-7000-8000-000000000001";

function reply(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

const SIGNER = {
  recipient_id: RECIPIENT,
  kind: "signer",
  name: "Maya Chen",
  email_masked: "m•••@example.com",
  title: "Mutual NDA · Maya Chen",
  document_name: "Mutual NDA",
  company: "Hale & Ward LLP",
  sender_name: "Rosa Hale",
  sender_email: "rosa@haleward.example",
  next: "verify",
  signed_at: null,
  disclosure: {
    version: "esign-disclosure-v1",
    agreement: "I agree to use electronic records and signatures.",
    paragraphs: [
      { title: "What this covers", text: "Hale & Ward LLP wants to give you this agreement." },
      { title: "A paper copy", text: "You may ask for a paper copy at any time by writing to rosa@haleward.example." },
    ],
  },
};

const EMPTY_DOCUMENT = {
  pages: [{ width: 612, height: 792 }],
  parties: [],
  fields: [],
  signatures: [],
  font: { id: "liberation-sans", family: "Liberation Sans", url: "/api/v1/fonts/liberation-sans" },
  fit: { min_size: 6, max_size: 12, baseline: 0.25, padding: 2 },
};

const problem = (status: number, code: string, title: string) => ({
  type: `/problems/${code}`,
  title,
  status,
  code,
  instance: "/api/v1/sign/open",
  request_id: "r",
});

function show(node: React.ReactNode) {
  render(<QueryClientProvider client={makeQueryClient()}>{node}</QueryClientProvider>);
}

describe("opening a signing link", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    replace.mockReset();
    forgetExchangesForTests();
  });

  it("exchanges the token once and moves to the clean address", async () => {
    fetchMock.mockImplementation(() => reply(200, { recipient_id: RECIPIENT, next: "verify" }));
    show(<OpenLink token="tok-1" />);

    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith(`/sign/${RECIPIENT}`));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("POST");
    expect(await request.json()).toEqual({ token: "tok-1" });
  });

  it("says a closed link is no longer open, and never why", async () => {
    fetchMock.mockImplementation(() =>
      reply(404, problem(404, "link-closed", "This request is no longer open")),
    );
    show(<OpenLink token="tok-2" />);

    expect(await screen.findByText("This request is no longer open.")).toBeTruthy();
    expect(screen.getByText("Nothing more is needed from you.")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("the signer's page", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("asks for consent with the disclosure, and goes on once the box is ticked", async () => {
    let consented = false;
    fetchMock.mockImplementation(async (input) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      if (path.endsWith("/document")) return reply(200, EMPTY_DOCUMENT);
      if (path.endsWith("/viewed")) return reply(200, null);
      if (request.method === "POST") {
        expect(await request.json()).toEqual({ disclosure_version: "esign-disclosure-v1" });
        consented = true;
        return reply(200, { recipient_id: RECIPIENT, next: "sign" });
      }
      return reply(200, { ...SIGNER, next: consented ? "sign" : "consent" });
    });
    show(<SignerPage recipientId={RECIPIENT} />);
    const user = userEvent.setup();

    expect(await screen.findByText("Before you read.")).toBeTruthy();
    expect(screen.getByText(/ask for a paper copy at any time/)).toBeTruthy();
    const proceed = screen.getByRole("button", { name: "Continue" });
    expect((proceed as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByLabelText("I agree to use electronic records and signatures."));
    await user.click(proceed);

    expect(await screen.findByRole("button", { name: "Approve" })).toBeTruthy(); // the document (nothing to fill)

  });

  it("thanks the signer, says when and how, offers a copy and says what is next", async () => {
    fetchMock.mockImplementation((input) => {
      const path = new URL((input as Request).url).pathname;
      if (path.endsWith("/done")) {
        return reply(200, { signed_at: "2026-11-11T17:14:22Z", verified_by: "email_code", waiting_for: ["Leo Chen"], countersigning: "Hale & Ward LLP" });
      }
      return reply(200, { ...SIGNER, next: "done", signed_at: "2026-11-11T17:14:22Z" });
    });
    show(<SignerPage recipientId={RECIPIENT} />);

    expect(await screen.findByText("Signed. Thank you, Maya.")).toBeTruthy();
    expect(screen.getByText("Email code to m•••@example.com")).toBeTruthy();
    const copy = screen.getByRole("link", { name: "Download a copy" });
    expect(copy.getAttribute("href")).toBe(`/api/v1/sign/${RECIPIENT}/copy.pdf`);
    expect(copy.hasAttribute("download")).toBe(true);
    expect(screen.getByText("Waiting for Leo Chen to sign, then Hale & Ward LLP countersigns. You'll get the completed copy by email.")).toBeTruthy();
  });

  it("asks to open the link again when the session ended", async () => {
    fetchMock.mockImplementation(() =>
      reply(401, problem(401, "session-ended", "Your session ended")),
    );
    show(<SignerPage recipientId={RECIPIENT} />);

    expect(await screen.findByText("Your session ended.")).toBeTruthy();
  });
});

describe("the email code", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  const state = (next: string) => ({ ...SIGNER, next });

  it("sends a code as the step opens and goes on once the six digits are right", async () => {
    let verified = false;
    const paths: string[] = [];
    fetchMock.mockImplementation(async (input) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      paths.push(`${request.method} ${path}`);
      if (path.endsWith("/code")) {
        return reply(200, { sent_at: "2026-11-11T08:00:00Z", email_masked: "m•••@example.com", resend_after: 60 });
      }
      if (path.endsWith("/verify")) {
        const { code } = (await request.json()) as { code: string };
        if (code !== "123456") {
          return reply(422, {
            ...problem(422, "validation-failed", "Some fields are invalid"),
            errors: [{ field: "code", message: "That code isn't right. 4 tries left." }],
          });
        }
        verified = true;
        return reply(200, { recipient_id: RECIPIENT, next: "consent" });
      }
      return reply(200, state(verified ? "consent" : "verify"));
    });
    show(<SignerPage recipientId={RECIPIENT} />);
    const user = userEvent.setup();

    const field = await screen.findByLabelText("Code");
    expect(screen.getByText("We sent a 6-digit code to m•••@example.com. It works for 10 minutes.")).toBeTruthy();
    expect(field.getAttribute("autocomplete")).toBe("one-time-code");
    expect(await screen.findByRole("button", { name: /send a new code in \d+ s/i })).toBeTruthy();

    await user.type(field, "12-34-50");
    expect(await screen.findByText("That code isn't right. 4 tries left.")).toBeTruthy();
    await user.type(screen.getByLabelText("Code"), "123456");

    expect(await screen.findByText("Before you read.")).toBeTruthy();
    expect(paths.filter((p) => p.startsWith("POST") && p.endsWith("/code")).length).toBeGreaterThan(0);
    expect(paths).toContain(`POST /api/v1/sign/${RECIPIENT}/verify`);
  });
});
