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
const FIRM = "countersigner:p-firm";
const DATE = "field:f-date";
const URGENT = "field:f-urgent";
const COLLEAGUES = [
  { value: "rosa@firm.example", text: "Rosa Hale · rosa@firm.example" },
  { value: "leo@firm.example", text: "Leo Park · leo@firm.example" },
];
const COLUMNS = [
  { key: NAME, header: "Client name", kind: "text", required: true, options: [] },
  { key: EMAIL, header: "Client email", kind: "email", required: true, options: [] },
  { key: FIRM, header: "Firm countersigner", kind: "choice", required: true, options: COLLEAGUES },
  { key: DATE, header: "Effective date", kind: "date", required: true, options: [] },
  { key: URGENT, header: "Urgent", kind: "checkbox", required: false, options: [] },
];
type Cells = Record<string, string>;
const cells = (name: string, email: string, extra: Cells = {}): Cells => ({
  [NAME]: name,
  [EMAIL]: email,
  [FIRM]: "rosa@firm.example",
  [DATE]: "2026-12-01",
  ...extra,
});

/** The server's verdict on a row, as far as these tests need it. */
function judge(rowCells: Cells) {
  const problems: { key: string; message: string; level: string }[] = [];
  if (!/@.+\..+/.test(rowCells[EMAIL] ?? "")) problems.push({ key: EMAIL, message: "Enter a valid email address", level: "error" });
  if (!rowCells[FIRM]) problems.push({ key: FIRM, message: "Choose who countersigns as Firm", level: "error" });
  if (rowCells[URGENT] && rowCells[URGENT] !== "yes") problems.push({ key: URGENT, message: "Tick it or leave it", level: "error" });
  return problems;
}
const sheetOf = (rows: { row_no: number; cells: Cells }[]) => ({
  columns: COLUMNS,
  rows: rows.map((r) => ({ ...r, problems: judge(r.cells) })),
  problems: [],
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
  const checks: { rows: { row_no: number; cells: Cells }[] }[] = [];
  const batches: { body: { rows: { row_no: number; cells: Cells }[]; file_name: string; defaults: object }; key: string | null }[] = [];
  let parsed: unknown;
  /** Set to hold a check's answer back until the test lets it go. */
  let gate: Promise<void> | null;
  let batchAnswer: () => Promise<Response>;

  beforeEach(() => {
    checks.length = 0;
    batches.length = 0;
    gate = null;
    batchAnswer = () => reply(201, { id: "batch-1", status: "sending", total: 3, sent: 0, failed: 0, failures: [] });
    parsed = sheetOf([
      { row_no: 2, cells: cells("Maya Chen", "maya@example.com") },
      { row_no: 3, cells: cells("Sam Roe", "sam@") },
      { row_no: 4, cells: cells("Ana Diaz", "ana@example.com") },
    ]);
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
        if (gate) await gate;
        return reply(200, sheetOf(body.rows));
      }
      if (request.method === "POST" && path.endsWith("/envelope-batches")) {
        batches.push({
          body: (await request.clone().json()) as (typeof batches)[number]["body"],
          key: request.headers.get("Idempotency-Key"),
        });
        return batchAnswer();
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
  const nextIsOpen = () =>
    waitFor(() => expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(false));
  /** Opens the dialog, picks the template and uploads the file the server will read as ``parsed``. */
  const uploaded = async () => {
    const view = open();
    await userEvent.click(screen.getByRole("button", { name: "Mutual NDA" }));
    await nextIsOpen();
    await next();
    const input = view.container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("no file input");
    await userEvent.upload(input, new File(["x"], "clients.csv", { type: "text/csv" }));
    return view;
  };
  const currentStep = () =>
    within(screen.getByRole("list", { name: "Steps" }))
      .getAllByRole("listitem")
      .find((item) => item.getAttribute("aria-current") === "step")?.textContent;

  it("offers each approved template's spreadsheet, and the way across to a single send", async () => {
    const { onSendOne } = open();

    const link = screen.getByRole("link", { name: "Download the spreadsheet for Mutual NDA" });
    expect(link.getAttribute("href")).toBe("/api/v1/documents/doc-1/versions/v-2/bulk-template");
    expect(link).toHaveAttribute("download");
    expect(link).toHaveTextContent("Template");
    // A template that is not approved has no spreadsheet to give.
    expect(screen.queryByRole("link", { name: "Download the spreadsheet for Draft letter" })).toBeNull();
    // Four steps: who countersigns is each row's own, not a step.
    expect(within(screen.getByRole("list", { name: "Steps" })).getAllByRole("listitem")).toHaveLength(4);

    await userEvent.click(screen.getByRole("button", { name: "Send one instead" }));
    expect(onSendOne).toHaveBeenCalledOnce();
  });

  it("shows the rows with problems in a table, clears one when its cell is fixed, and sends the rest", async () => {
    const { onSent } = await uploaded();
    const user = userEvent.setup();

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
    await nextIsOpen();
    await next();

    // Review: what goes out, who countersigns as the rows say, the settings; then send, once.
    expect(currentStep()).toContain("Review");
    expect(screen.getByText("2 envelopes, one for each row of clients.csv")).toBeInTheDocument();
    expect(screen.getByText("Firm countersigns").nextElementSibling).toHaveTextContent("Rosa Hale");
    expect(screen.getByText("1 row is left out and will not be sent")).toBeInTheDocument();
    expect(screen.getByLabelText("Expires after (days)")).toHaveValue("14");
    await user.click(screen.getByRole("button", { name: "Send 2 envelopes" }));
    await waitFor(() => expect(onSent).toHaveBeenCalledOnce());
    expect(batches).toHaveLength(1);
    expect(batches[0]?.body.rows.map((r) => r.row_no)).toEqual([2, 4]);
    expect(batches[0]?.body.file_name).toBe("clients.csv");
    expect(batches[0]?.body.defaults).not.toHaveProperty("countersigners");
    expect(batches[0]?.key).toBeTruthy();
  });

  it("goes straight to the review when the file has no problems", async () => {
    parsed = sheetOf([{ row_no: 2, cells: cells("Maya Chen", "maya@example.com") }]);
    await uploaded();

    expect(await screen.findByText("1 envelope, one for each row of clients.csv")).toBeInTheDocument();
    expect(currentStep()).toContain("Review");
  });

  it("says what is wrong with a file whose columns are not the template's", async () => {
    parsed = { columns: [], rows: [], problems: ['This file has a column "Shoe size" that this template does not ask for'] };
    await uploaded();

    expect(await screen.findByText("clients.csv does not match this template")).toBeInTheDocument();
    expect(screen.getByText(/Shoe size/)).toBeInTheDocument();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("asks who countersigns in the table when the rows do not say, one choice for all of them", async () => {
    // Finding 1: no step chooses a countersigner after the table; the table is where it is fixed.
    parsed = sheetOf([
      { row_no: 2, cells: cells("Maya Chen", "maya@example.com", { [FIRM]: "" }) },
      { row_no: 3, cells: cells("Sam Roe", "sam@example.com", { [FIRM]: "" }) },
      { row_no: 4, cells: cells("Ana Diaz", "ana@example.com", { [FIRM]: "leo@firm.example" }) },
    ]);
    await uploaded();
    const user = userEvent.setup();

    const own = await screen.findByRole("combobox", { name: "Firm countersigner, row 2" });
    expect(own).toHaveAccessibleDescription("Choose who countersigns as Firm");
    expect(screen.getByRole("status")).toHaveTextContent("2 of 3 rows need fixing");

    await user.selectOptions(screen.getByRole("combobox", { name: "Firm countersigner: set for every empty row" }), "rosa@firm.example");

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("All 3 rows are ready to send"));
    expect(checks.at(-1)?.rows.map((r) => r.cells[FIRM])).toEqual(["rosa@firm.example", "rosa@firm.example", "leo@firm.example"]);
    // With nothing left empty the heading's choice goes away.
    expect(screen.queryByRole("combobox", { name: "Firm countersigner: set for every empty row" })).toBeNull();
    await nextIsOpen();
    await next();
    expect(screen.getByText("Firm countersigns").nextElementSibling).toHaveTextContent("Rosa Hale (2 rows), Leo Park (1 row)");
  });

  it("keeps what is typed while a check is on its way", async () => {
    // Finding 2: a check's answer is about the rows as they were sent; it must not undo an edit since.
    parsed = sheetOf([
      { row_no: 2, cells: cells("Maya Chen", "maya@") },
      { row_no: 3, cells: cells("Sam Roe", "sam@") },
    ]);
    await uploaded();
    const user = userEvent.setup();
    let release = () => {};
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    const first = await screen.findByRole("textbox", { name: "Client email, row 2" });
    await user.clear(first);
    await user.type(first, "maya@example.com");
    const second = screen.getByRole("textbox", { name: "Client email, row 3" });
    await user.click(second); // leaves the first cell: a check goes out
    await waitFor(() => expect(checks).toHaveLength(1));
    await user.clear(second);
    await user.type(second, "sam@example.com"); // typed while that check is still out
    gate = null;
    release();

    // The first answer did not put "sam@" back, and the edit made since is checked in its turn.
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 of 2 rows needs fixing"));
    expect(screen.getByRole("textbox", { name: "Client email, row 3" })).toHaveValue("sam@example.com");
    await user.tab();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("All 2 rows are ready to send"));
    expect(checks.at(-1)?.rows.map((r) => r.cells[EMAIL])).toEqual(["maya@example.com", "sam@example.com"]);
  });

  it("lets a tick be corrected in the table", async () => {
    // Finding 3: the check that follows a tick must see the tick.
    parsed = sheetOf([{ row_no: 2, cells: cells("Maya Chen", "maya@example.com", { [URGENT]: "maybe" }) }]);
    await uploaded();
    const user = userEvent.setup();

    const tick = await screen.findByRole("checkbox", { name: "Urgent, row 2" });
    expect(tick).toHaveAccessibleDescription("Tick it or leave it");
    await user.click(tick);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("All 1 row is ready to send"));
    expect(checks.at(-1)?.rows[0]?.cells[URGENT]).toBe("yes");
    expect(screen.getByRole("checkbox", { name: "Urgent, row 2" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Urgent, row 2" })).not.toHaveAttribute("aria-invalid");
  });

  it("shows the rows the server refuses at send, under the same filter", async () => {
    // Finding 4: the list of rows with problems follows the rows, not what it held when it opened.
    parsed = sheetOf([
      { row_no: 2, cells: cells("Maya Chen", "maya@example.com") },
      { row_no: 3, cells: cells("Sam Roe", "sam@") },
    ]);
    await uploaded();
    const user = userEvent.setup();
    const cell = await screen.findByRole("textbox", { name: "Client email, row 3" });
    await user.clear(cell);
    await user.type(cell, "sam@example.com");
    await user.tab();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("All 2 rows are ready to send"));
    await nextIsOpen();
    await next();

    // Between the check and the send, the colleague who countersigns row 2 left the company.
    batchAnswer = () =>
      reply(422, { type: "/problems/bulk-rows-need-fixing", title: "Some rows still have problems", status: 422, code: "bulk-rows-need-fixing" });
    const judgeNow = fetchMock.getMockImplementation();
    fetchMock.mockImplementation(async (input, init) => {
      const request = input as Request;
      if (!new URL(request.url).pathname.endsWith("/bulk-rows/check")) return judgeNow!(input, init);
      const body = (await request.clone().json()) as (typeof checks)[number];
      return reply(200, {
        columns: COLUMNS,
        rows: body.rows.map((r) => ({
          ...r,
          problems: r.row_no === 2 ? [{ key: FIRM, message: "Not a colleague's email", level: "error" }] : [],
        })),
        problems: [],
      });
    });
    await user.click(screen.getByRole("button", { name: "Send 2 envelopes" }));

    expect(await screen.findByText("Some rows no longer pass")).toBeInTheDocument();
    const refusedCell = await screen.findByRole("combobox", { name: "Firm countersigner, row 2" });
    expect(refusedCell).toHaveAccessibleDescription("Not a colleague's email");
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2 rows needs fixing");
    expect(screen.queryByText("No rows with problems.")).toBeNull();
  });
});
