import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";

import { SendModal, type SendableDocument } from "./SendModal";
import { MEASURED_AT } from "./typeset";

vi.mock("pdfjs-dist", () => ({
  version: "6.4.299",
  GlobalWorkerOptions: {},
  getDocument: () => ({ promise: new Promise(() => {}), destroy: vi.fn() }),
}));

const field = (id: string, label: string, holds: string, extra: Record<string, unknown> = {}) => ({
  id,
  label,
  holds,
  holds_label: null,
  party_id: null,
  required: false,
  sensitive: false,
  options: [],
  depends_on: null,
  places: [{ page: 1, rect: [100, 100, 200, 120], option_value: null, text_size: 10 }],
  from_recipient: null,
  ...extra,
});

const FORM = {
  document_id: "doc-1",
  document_name: "Mutual NDA",
  version_id: "v-2",
  version_number: 2,
  pages: [{ width: 595, height: 842 }],
  signers: [
    {
      party_id: "p-client",
      label: "Client",
      kind_label: null,
      position: 1,
    },
  ],
  countersigners: [
    {
      party_id: "p-firm",
      label: "Firm",
      position: 2,
      default: { user_id: "u-rosa", name: "Rosa Hale", email: "rosa@firm.example" },
    },
  ],
  fields: [
    field("f-name", "Client name", "full_name", { party_id: "p-client", from_recipient: "name" }),
    field("f-email", "Client email", "email", { party_id: "p-client", from_recipient: "email" }),
    field("f-company", "Client company", "company", { party_id: "p-client" }),
    field("f-date", "Effective date", "date", { required: true }),
    field("f-plan", "Plan", "choice", {
      options: [
        { value: "Gold", text: "Gold plan" },
        { value: "Silver", text: "Silver plan" },
      ],
    }),
    field("f-card", "Card", "text", { depends_on: { field_id: "f-plan", option: "Gold" } }),
  ],
  settings: { require_email_code: true, reminder_interval_hours: 24, max_reminders: 5, expiry_days: 14, notify_emails: [] },
  font: { id: "liberation-sans", family: "Liberation Sans", url: "/api/v1/fonts/liberation-sans" },
  fit: { min_size: 6, fallback_ratio: 0.72, fallback_cap: 11, baseline_ratio: 0.18, baseline_min: 1.5 },
};

const DOCUMENTS: SendableDocument[] = [
  { id: "doc-1", name: "Mutual NDA", kind: "pdf", page_count: 2, current_version: { id: "v-2", number: 2 } },
  { id: "doc-2", name: "Draft letter", kind: "docx", page_count: 1, current_version: null },
];
const COLLEAGUES = [
  { id: "u-rosa", name: "Rosa Hale", email: "rosa@firm.example" },
  { id: "u-leo", name: "Leo Park", email: "leo@firm.example" },
];

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}

describe("the send", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const sent: { body: unknown; key: string | null }[] = [];
  let answer: () => Promise<Response>;

  beforeEach(() => {
    sent.length = 0;
    answer = () => reply(201, { id: "env-1" });
    Element.prototype.scrollTo = vi.fn() as unknown as Element["scrollTo"];
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (input) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      if (path.endsWith("/send-form")) return reply(200, FORM);
      if (request.method === "POST" && path.endsWith("/envelopes")) {
        sent.push({ body: await request.clone().json(), key: request.headers.get("Idempotency-Key") });
        return answer();
      }
      return reply(404, {});
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  const open = (props: Partial<Parameters<typeof SendModal>[0]> = {}) => {
    const onSent = vi.fn();
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <SendModal documents={DOCUMENTS} colleagues={COLLEAGUES} onClose={onClose} onSent={onSent} {...props} />
      </QueryClientProvider>,
    );
    return { onSent, onClose };
  };
  const next = () => userEvent.click(screen.getByRole("button", { name: "Next" }));

  it("walks the five steps and sends what was filled; the signer's own name and email are never asked", async () => {
    const { onSent } = open();
    const user = userEvent.setup();
    const steps = screen.getByRole("list", { name: "Steps" });
    expect(within(steps).getByText("Template").closest("li")?.getAttribute("aria-current")).toBe("step");

    // 1. Only an approved document can be chosen.
    expect((screen.getByRole("button", { name: "Draft letter" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "Mutual NDA" }));
    expect(screen.getByRole("button", { name: "Mutual NDA" }).getAttribute("aria-pressed")).toBe("true");
    await next();

    // 2. Details: optional, except what only the sender can fill; a condition hides its field; the
    //    signer's name and email are theirs (the email from the send, the name when they sign).
    await screen.findByLabelText("Client company");
    expect(screen.queryByLabelText("Client name")).toBeNull();
    expect(screen.queryByLabelText("Client email")).toBeNull();
    expect(screen.queryByLabelText("Card")).toBeNull();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
    await user.type(screen.getByLabelText("Client company"), "Chen Studio");
    await user.type(screen.getByLabelText("Effective date"), "2026-12-01");
    await next();

    // 3. Signers: typed here; someone receives a copy.
    expect(screen.getByText("Signer 1 · Client")).toBeTruthy();
    await user.type(screen.getByLabelText("Name"), "Maya Chen");
    await user.type(screen.getByLabelText("Email"), "maya@example.com");
    await user.click(screen.getByRole("button", { name: "+ Add someone" }));
    const copyName = screen.getAllByLabelText("Name")[1] as HTMLInputElement;
    await user.type(copyName, "Records");
    await user.type(screen.getAllByLabelText("Email")[1] as HTMLInputElement, "records@firm.example");
    await next();

    // 4. Countersigners: the department's by default.
    expect(screen.getByText("Rosa Hale is emailed once every signer has signed.")).toBeTruthy();
    await next();

    // 5. Review, then send.
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe("Mutual NDA · Maya Chen");
    expect(screen.getByText("Countersigner 1: Rosa Hale")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Mutual NDA with the values you filled in" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Send envelope" }));

    await waitFor(() => expect(onSent).toHaveBeenCalledWith({ id: "env-1" }));
    expect(onSent).toHaveBeenCalledTimes(1);
    const [request] = sent;
    expect(request?.key).toBeTruthy();
    expect(request?.body).toEqual({
      version_id: "v-2",
      title: "Mutual NDA · Maya Chen",
      signers: [{ party_id: "p-client", name: "Maya Chen", email: "maya@example.com" }],
      countersigners: [{ party_id: "p-firm", user_id: "u-rosa" }],
      copies: [{ name: "Records", email: "records@firm.example" }],
      values: [
        { field_id: "f-company", value: "Chen Studio" },
        { field_id: "f-date", value: "2026-12-01" },
      ],
      settings: FORM.settings,
      confirm_same_person: false,
      time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone, // the sender's, for the emails' dates
    });
  });

  it("starts at the details from a document, and takes the server's problems back to their step", async () => {
    answer = () =>
      reply(422, {
        type: "x",
        title: "Some fields are invalid",
        status: 422,
        code: "validation-failed",
        errors: [{ field: "fields.f-date", message: "Enter a date" }],
      });
    open({ initialDocumentId: "doc-1" });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Effective date"), "2026-12-01");
    await next();
    await user.type(screen.getByLabelText("Name"), "Maya Chen");
    await user.type(screen.getByLabelText("Email"), "maya@example.com");
    await next();
    await next();
    await user.click(screen.getByRole("button", { name: "Send envelope" }));

    await user.click(await screen.findByRole("button", { name: "Go to Details" }));
    expect(screen.getByText("Enter a date")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull(); // started at the details
  });

  const toReview = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.type(await screen.findByLabelText("Effective date"), "2026-12-01");
    await next();
    await user.type(screen.getByLabelText("Name"), "Maya Chen");
    await user.type(screen.getByLabelText("Email"), "maya@example.com");
    await next();
    await next();
  };

  it("says a setting's rule at its box and sends nothing until it is a number in range", async () => {
    open({ initialDocumentId: "doc-1" });
    const user = userEvent.setup();
    await toReview(user);
    const expiry = screen.getByLabelText<HTMLInputElement>("Expires after (days)");
    await user.clear(expiry);
    expect(expiry.value).toBe(""); // an empty box stays empty: it was sent as 0 days
    await user.click(screen.getByRole("button", { name: "Send envelope" }));

    expect(screen.getByText("Enter a whole number from 1 to 365")).toBeTruthy();
    expect(expiry.closest("details")?.open).toBe(true); // the box with the problem is on show
    expect(sent).toHaveLength(0);

    await user.type(expiry, "400");
    expect(screen.getByText("Enter a whole number from 1 to 365")).toBeTruthy();
    await user.clear(expiry);
    await user.type(expiry, "30");
    expect(screen.queryByText("Enter a whole number from 1 to 365")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Send envelope" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.body).toMatchObject({ settings: { expiry_days: 30, max_reminders: 5, reminder_interval_hours: 24 } });
  });

  it("shows the server's word for any setting at its box", async () => {
    answer = () =>
      reply(422, {
        type: "x",
        title: "Some fields are invalid",
        status: 422,
        code: "validation-failed",
        errors: [
          { field: "settings.max_reminders", message: "Input should be less than or equal to 20" },
          { field: "settings.expiry_days", message: "Input should be greater than or equal to 1" },
        ],
      });
    open({ initialDocumentId: "doc-1" });
    const user = userEvent.setup();
    await toReview(user);
    await user.click(screen.getByRole("button", { name: "Send envelope" }));

    expect(await screen.findByText("Input should be less than or equal to 20")).toBeTruthy();
    expect(screen.getByText("Input should be greater than or equal to 1")).toBeTruthy();
    expect(screen.getByLabelText("Reminders at most").closest("details")?.open).toBe(true);
  });

  it("says when no party signs first, where the signers would be", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = new URL((input as Request).url).pathname;
      return path.endsWith("/send-form") ? reply(200, { ...FORM, signers: [], fields: [] }) : reply(404, {});
    });
    open({ initialDocumentId: "doc-1" });
    await screen.findByText("Nothing to fill in before sending.");
    await next();
    expect(screen.getByText("No party signs this template first, so nobody is emailed a link to sign.")).toBeTruthy();
  });

  it("asks before sending one person as two parties", async () => {
    answer = () =>
      sent.length === 1
        ? reply(409, { type: "x", title: "Same", status: 409, code: "same-person", detail: "rosa@firm.example" })
        : reply(201, { id: "env-2" });
    const { onSent } = open({ initialDocumentId: "doc-1" });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Effective date"), "2026-12-01");
    await next();
    await user.type(screen.getByLabelText("Name"), "Rosa Hale");
    await user.type(screen.getByLabelText("Email"), "rosa@firm.example");
    await next();
    await next();
    await user.click(screen.getByRole("button", { name: "Send envelope" }));

    expect(await screen.findByText("rosa@firm.example is on two parties. Send anyway if one person signs as both.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Send anyway" }));
    await waitFor(() => expect(onSent).toHaveBeenCalledWith({ id: "env-2" }));
    expect((sent[1]?.body as { confirm_same_person: boolean }).confirm_same_person).toBe(true);
  });

  it("says when a value is too long for its box, and holds Next until it fits", async () => {
    // Every character half a point wide per point of size (the test DOM cannot measure text).
    const measure = vi
      .spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue({ font: "", measureText: (t: string) => ({ width: t.length * 0.5 * MEASURED_AT }) } as unknown as CanvasRenderingContext2D);
    // The envelope's font arrives (the test DOM has no FontFace): widths are judged only in it.
    vi.stubGlobal(
      "FontFace",
      class {
        load() {
          return Promise.resolve(this);
        }
      },
    );
    Object.defineProperty(document, "fonts", { value: { add: () => {} }, configurable: true });
    open({ initialDocumentId: "doc-1" });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Effective date"), "2026-12-01");
    // The company box is 100 pt wide: at 10 pt down to 6 pt, 33 characters fit, not 40.
    await user.type(screen.getByLabelText("Client company"), "x".repeat(40));

    expect(await screen.findByText("Too long for its box")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
    await user.clear(screen.getByLabelText("Client company"));
    await user.type(screen.getByLabelText("Client company"), "Chen Studio");
    expect(screen.queryByText("Too long for its box")).toBeNull();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(false);
    measure.mockRestore();
    vi.unstubAllGlobals();
  });

  it("says a document needs approval instead of an empty step", async () => {
    open({ initialDocumentId: "doc-2" }); // a document with no approved version
    expect(await screen.findByText("Draft letter needs approval")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("asks before closing once something is filled in", async () => {
    const { onClose } = open({ initialDocumentId: "doc-1" });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Effective date"), "2026-12-01");
    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("Close without sending?")).toBeTruthy();
    const close = screen.getAllByRole("button", { name: "Close" });
    await user.click(close[close.length - 1] as HTMLElement);
    expect(onClose).toHaveBeenCalled();
  });
});
