import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";

import { BulkSendModal } from "./BulkSendModal";
import type { SendableDocument } from "./SendModal";

const FORM = {
  document_id: "doc-1",
  document_name: "Mutual NDA",
  version_id: "v-2",
  version_number: 2,
  pages: [{ width: 595, height: 842 }],
  signers: [{ party_id: "p-client", label: "Client", kind_label: null, position: 1 }],
  countersigners: [
    {
      party_id: "p-firm",
      label: "Firm",
      position: 2,
      default: { user_id: "u-rosa", name: "Rosa Hale", email: "rosa@firm.example" },
    },
  ],
  colleagues: [
    { user_id: "u-rosa", name: "Rosa Hale", email: "rosa@firm.example" },
    { user_id: "u-leo", name: "Leo Park", email: "leo@firm.example" },
  ],
  fields: [],
  settings: { require_email_code: true, reminder_interval_hours: 24, max_reminders: 5, expiry_days: 14, notify_emails: [] },
  font: { id: "liberation-sans", family: "Liberation Sans", url: "/api/v1/fonts/liberation-sans" },
  fit: { min_size: 6, fallback_ratio: 0.72, fallback_cap: 11, baseline_ratio: 0.18, baseline_min: 1.5 },
};

const NAME = "signer:p-client:name";
const EMAIL = "signer:p-client:email";
const DATE = "field:f-date";
const COLUMNS = [
  { key: NAME, header: "Client name", kind: "text", required: true, options: [] },
  { key: EMAIL, header: "Client email", kind: "email", required: true, options: [] },
  { key: DATE, header: "Effective date", kind: "date", required: true, options: [] },
];
const row = (row_no: number, name: string, email: string, problems: unknown[] = []) => ({
  row_no,
  cells: { [NAME]: name, [EMAIL]: email, [DATE]: "2026-12-01" },
  problems,
});

const DOCUMENTS: SendableDocument[] = [
  { id: "doc-1", name: "Mutual NDA", kind: "pdf", page_count: 2, current_version: { id: "v-2", number: 2 } },
  { id: "doc-2", name: "Draft letter", kind: "docx", page_count: 1, current_version: null },
];

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}

describe("the bulk send", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const checks: { rows: { row_no: number; cells: Record<string, string> }[] }[] = [];
  const batches: { body: { rows: { row_no: number }[]; file_name: string }; key: string | null }[] = [];
  let parsed: unknown;

  beforeEach(() => {
    checks.length = 0;
    batches.length = 0;
    parsed = {
      columns: COLUMNS,
      rows: [
        row(2, "Maya Chen", "maya@example.com"),
        row(3, "Sam Roe", "sam@", [{ key: EMAIL, message: "Enter a valid email address", level: "error" }]),
        row(4, "Ana Diaz", "ana@example.com"),
      ],
      problems: [],
    };
    Element.prototype.scrollTo = vi.fn() as unknown as Element["scrollTo"];
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (input) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      if (path.endsWith("/send-form")) return reply(200, FORM);
      if (path.endsWith("/bulk-rows")) return reply(200, parsed);
      if (path.endsWith("/bulk-rows/check")) {
        const body = (await request.clone().json()) as (typeof checks)[number];
        checks.push(body);
        // The server's verdict: an email with a dot after the @ passes.
        return reply(200, {
          columns: COLUMNS,
          rows: body.rows.map((r) => ({
            ...r,
            problems: /@.+\..+/.test(r.cells[EMAIL] ?? "")
              ? []
              : [{ key: EMAIL, message: "Enter a valid email address", level: "error" }],
          })),
          problems: [],
        });
      }
      if (request.method === "POST" && path.endsWith("/envelope-batches")) {
        batches.push({
          body: (await request.clone().json()) as (typeof batches)[number]["body"],
          key: request.headers.get("Idempotency-Key"),
        });
        return reply(201, { id: "batch-1", status: "sending", total: 3, sent: 0, failed: 0, failures: [] });
      }
      return reply(404, {});
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  const open = () => {
    const onSent = vi.fn();
    const onSendOne = vi.fn();
    const view = render(
      <QueryClientProvider client={makeQueryClient()}>
        <BulkSendModal
          documents={DOCUMENTS}
          editHref={(id) => `/departments/d-1/documents/${id}`}
          onClose={vi.fn()}
          onSent={onSent}
          onSendOne={onSendOne}
        />
      </QueryClientProvider>,
    );
    return { onSent, onSendOne, ...view };
  };
  const next = () => userEvent.click(screen.getByRole("button", { name: "Next" }));
  const upload = async (container: HTMLElement) => {
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("no file input");
    await userEvent.upload(input, new File(["x"], "clients.csv", { type: "text/csv" }));
  };

  it("offers each approved template's spreadsheet, and the way across to a single send", async () => {
    const { onSendOne } = open();

    const link = screen.getByRole("link", { name: "Download the spreadsheet for Mutual NDA" });
    expect(link.getAttribute("href")).toBe("/api/v1/documents/doc-1/versions/v-2/bulk-template");
    expect(link).toHaveAttribute("download");
    expect(link).toHaveTextContent("Template");
    // A template that is not approved has no spreadsheet to give.
    expect(screen.queryByRole("link", { name: "Download the spreadsheet for Draft letter" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Send one instead" }));
    expect(onSendOne).toHaveBeenCalledOnce();
  });

  it("shows the rows with problems in a table, clears one when its cell is fixed, and sends the rest", async () => {
    const { onSent, container } = open();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Mutual NDA" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(false));
    await next();

    // Upload: the spreadsheet is offered here too, at the step's top.
    expect(screen.getByRole("link", { name: "Download the spreadsheet for Mutual NDA" })).toBeInTheDocument();
    await upload(container);

    // Fix: the file has a problem, so the dialog opens on the table, and the stop shows the count.
    const cell = await screen.findByRole("textbox", { name: "Client email, row 3" });
    expect(cell).toHaveAttribute("aria-invalid", "true");
    expect(cell).toHaveAccessibleDescription("Enter a valid email address");
    expect(screen.getByRole("status")).toHaveTextContent("1 of 3 rows needs fixing");
    const steps = screen.getByRole("list", { name: "Steps" });
    expect(within(steps).getByText("Fix").closest("li")).toHaveTextContent("1");
    // Only the rows with problems are listed, and the way on is closed.
    expect(screen.queryByRole("textbox", { name: "Client email, row 2" })).toBeNull();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);

    // Correcting the cell and leaving it has the rows checked again, by the server.
    await user.clear(cell);
    await user.type(cell, "sam@example.com");
    await user.tab();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("All 3 rows are ready to send"));
    expect(checks.at(-1)?.rows.find((r) => r.row_no === 3)?.cells[EMAIL]).toBe("sam@example.com");
    expect(screen.getByRole("textbox", { name: "Client email, row 3" })).not.toHaveAttribute("aria-invalid");

    // A row can be left out: it is not sent.
    await user.click(screen.getByRole("button", { name: "Leave out row 3" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 left out"));
    await next();

    // Send to: the department's countersigner and settings, chosen once.
    expect(await screen.findByText("For every row that does not name its own.")).toBeInTheDocument();
    await next();

    // Review, then send: the rows kept, once.
    expect(screen.getByText("2 envelopes, one for each row of clients.csv")).toBeInTheDocument();
    expect(screen.getByText("1 row is left out and will not be sent")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send 2 envelopes" }));
    await waitFor(() => expect(onSent).toHaveBeenCalledOnce());
    expect(batches).toHaveLength(1);
    expect(batches[0]?.body.rows.map((r) => r.row_no)).toEqual([2, 4]);
    expect(batches[0]?.body.file_name).toBe("clients.csv");
    expect(batches[0]?.key).toBeTruthy();
  });

  it("goes straight past Fix when the file has no problems", async () => {
    parsed = { columns: COLUMNS, rows: [row(2, "Maya Chen", "maya@example.com")], problems: [] };
    const { container } = open();
    await userEvent.click(screen.getByRole("button", { name: "Mutual NDA" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(false));
    await next();
    await upload(container);

    expect(await screen.findByText("For every row that does not name its own.")).toBeInTheDocument();
    const steps = screen.getByRole("list", { name: "Steps" });
    expect(within(steps).getByText("Send to").closest("li")?.getAttribute("aria-current")).toBe("step");
  });

  it("says what is wrong with a file whose columns are not the template's", async () => {
    parsed = { columns: [], rows: [], problems: ['This file has a column "Shoe size" that this template does not ask for'] };
    const { container } = open();
    await userEvent.click(screen.getByRole("button", { name: "Mutual NDA" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(false));
    await next();
    await upload(container);

    expect(await screen.findByText("clients.csv does not match this template")).toBeInTheDocument();
    expect(screen.getByText(/Shoe size/)).toBeInTheDocument();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
