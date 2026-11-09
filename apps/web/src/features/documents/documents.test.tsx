import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import { clearHandOff, handOff, processingInterval } from "./api";
import { DocumentsSection } from "./DocumentsSection";
import { FakeUpload } from "./fakeUpload.testing";
import { UploadPage } from "./UploadPage";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const FINANCE = { id: "d-1", name: "Finance", status: "active", access: "edit" } as const;
const META = { version: "1", commit: "x", password_min_length: 12, password_rule: "x", document_max_bytes: 50 * 1024 * 1024, document_max_pages: 200 };

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}

const summary = (overrides: Record<string, unknown> = {}) => ({
  id: "doc-1",
  name: "Engagement letter",
  description: "",
  kind: "pdf",
  page_count: 7,
  current_version: { id: "v-1", number: 2 },
  latest_version: { id: "v-1", number: 2, status: "ready", created_at: "2026-11-07T10:00:00Z" },
  updated_at: "2026-11-07T10:00:00Z",
  archived_at: null,
  ...overrides,
});

const detail = (status: string) => ({
  ...summary({ current_version: null, latest_version: { id: "v-1", number: 1, status, created_at: new Date().toISOString() } }),
  department_id: "d-1",
  require_email_code: true,
  created_by: { id: "u", name: "Rosa Hale" },
  created_at: "2026-11-07T10:00:00Z",
  access: "edit",
  versions: [
    {
      id: "v-1",
      number: 1,
      status,
      problem: null,
      kind: "pdf",
      filename: "Letter.pdf",
      bytes: 100,
      page_count: null,
      pages_without_text: [],
      ai_instructions: "",
      uploaded_by: { id: "u", name: "Rosa Hale" },
      created_at: new Date().toISOString(),
      processed_at: null,
      is_current: false,
    },
  ],
});

const uploaded = (overrides: Record<string, unknown> = {}) => ({
  id: "up-1",
  filename: "Engagement letter v3.pdf",
  kind: "pdf",
  bytes: 8,
  suggested_name: "Engagement letter v3",
  expires_at: "2026-11-08T10:00:00Z",
  duplicate: null,
  ...overrides,
});

function wrap(node: ReactNode) {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

const pdf = (name = "Engagement letter v3.pdf") => new File(["%PDF-1.7"], name, { type: "application/pdf" });

describe("documents", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const posted: { url: string; body: unknown; key: string | null }[] = [];

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("XMLHttpRequest", FakeUpload);
    FakeUpload.sent = [];
    META.document_max_bytes = 50 * 1024 * 1024;
    posted.length = 0;
    clearHandOff("d-1");
    push.mockReset();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  function serve(routes: { documents?: unknown[]; create?: () => Promise<Response>; document?: unknown }) {
    fetchMock.mockImplementation(async (input) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      if (path.endsWith("/meta")) return reply(200, META);
      if (request.method === "POST" && path.endsWith("/documents")) {
        posted.push({ url: path, body: await request.clone().json(), key: request.headers.get("Idempotency-Key") });
        return routes.create ? routes.create() : reply(201, detail("processing"));
      }
      if (path.endsWith("/documents")) return reply(200, routes.documents ?? []);
      return reply(200, routes.document ?? detail("processing"));
    });
  }

  it("polls quickly while something has just started processing, then less, then not at all", () => {
    const now = Date.parse("2026-11-07T10:01:00Z");
    expect(processingInterval([], now)).toBe(false);
    expect(processingInterval(["2026-11-07T10:00:55Z"], now)).toBe(1_000);
    expect(processingInterval(["2026-11-07T10:00:30Z"], now)).toBe(2_000);
    expect(processingInterval(["2026-11-07T09:00:00Z"], now)).toBe(5_000);
  });

  it("lists documents with their version and status in plain words", async () => {
    serve({ documents: [summary(), summary({ id: "doc-2", name: "NDA", kind: "docx", page_count: 1, latest_version: { id: "v-9", number: 3, status: "needs_password", created_at: "2026-11-07T10:00:00Z" } })] });
    wrap(<DocumentsSection departmentId="d-1" canEdit={false} />);

    const list = await screen.findByRole("region", { name: "Documents list" });
    const letter = within(list).getByText("Engagement letter").closest("tr") as HTMLElement;
    expect(within(letter).getByText("PDF · 7 pages")).toBeTruthy();
    expect(within(letter).getByText("v2")).toBeTruthy();
    expect(within(letter).getByText("Ready")).toBeTruthy();
    expect(within(list).getByText("Word → PDF · 1 page")).toBeTruthy();
    expect(within(list).getByText("Needs password")).toBeTruthy();
    expect(screen.queryByLabelText(/Drop a PDF or Word file/)).toBeNull(); // read access: no dropzone
  });

  it("opens the upload page with a file dropped on the department page", async () => {
    serve({ documents: [] });
    wrap(<DocumentsSection departmentId="d-1" canEdit />);
    const file = pdf();

    await userEvent.setup().upload(await screen.findByLabelText(/Drop a PDF or Word file/), file);

    expect(push).toHaveBeenCalledWith("/departments/d-1/upload");
  });

  it("uploads, names from the file, and adds the document with its instructions", async () => {
    serve({});
    wrap(<UploadPage department={FINANCE} />);
    const user = userEvent.setup();

    await user.upload(await screen.findByLabelText(/Drop a PDF or Word file/), pdf());
    const transfer = FakeUpload.sent[0];
    expect(transfer?.url).toBe("/api/v1/departments/d-1/uploads?filename=Engagement%20letter%20v3.pdf");
    expect(screen.getByRole("progressbar", { name: "Uploading Engagement letter v3.pdf" })).toBeTruthy();
    transfer?.answer(201, uploaded());

    const name = (await screen.findByLabelText("Name")) as HTMLInputElement;
    expect(name.value).toBe("Engagement letter v3");
    await user.type(screen.getByLabelText("Instructions for the AI"), "Two clients sign.");
    await user.click(screen.getByRole("button", { name: "Add document" }));

    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]?.body).toEqual({
      name: "Engagement letter v3",
      ai_instructions: "Two clients sign.",
      upload_id: "up-1",
      allow_duplicate: false,
    });
    expect(posted[0]?.key).toBeTruthy();
    expect(await screen.findByText("Processing")).toBeTruthy(); // its live status
  });

  it("starts uploading files handed over from another page at once", async () => {
    serve({});
    handOff("d-1", [pdf("Handed over.pdf")]);
    wrap(<UploadPage department={FINANCE} />);
    await vi.waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    expect(FakeUpload.sent[0]?.url).toContain("filename=Handed%20over.pdf");
  });

  it("still uploads a handed-over file under development's double mount", async () => {
    serve({});
    handOff("d-1", [pdf("Handed over.pdf")]);
    wrap(
      <StrictMode>
        <UploadPage department={FINANCE} />
      </StrictMode>,
    );
    await vi.waitFor(() => expect(FakeUpload.sent.filter((transfer) => !transfer.aborted)).toHaveLength(1));
    FakeUpload.sent.find((transfer) => !transfer.aborted)?.answer(201, uploaded());

    expect(((await screen.findByLabelText("Name")) as HTMLInputElement).value).toBe("Engagement letter v3");
  });

  it("lets the next file upload while the first is still uploading", async () => {
    serve({});
    wrap(<UploadPage department={FINANCE} />);
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Drop a PDF or Word file/), pdf("One.pdf"));
    await user.upload(screen.getByLabelText(/Drop a PDF or Word file/), pdf("Two.pdf"));
    expect(FakeUpload.sent).toHaveLength(2);
    expect(screen.getAllByRole("progressbar")).toHaveLength(2);
  });

  it("asks about a file already in the department, and cancels without adding anything", async () => {
    serve({});
    wrap(<UploadPage department={FINANCE} />);
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Drop a PDF or Word file/), pdf());
    FakeUpload.sent[0]?.answer(201, uploaded({ duplicate: { document_id: "doc-1", document_name: "Engagement letter", version_number: 2, archived: false } }));

    expect(await screen.findByText("Engagement letter v3.pdf is already in Finance as Engagement letter, version 2. Upload it anyway as a separate document?")).toBeTruthy();
    // The dialog opens (showModal) in an effect: wait for its button, not only its words.
    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(await screen.findByText("Upload cancelled. Nothing was added.")).toBeTruthy();
    expect(posted).toHaveLength(0);
  });

  it("adds a duplicate as a separate document when the person says so", async () => {
    serve({});
    wrap(<UploadPage department={FINANCE} />);
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Drop a PDF or Word file/), pdf());
    FakeUpload.sent[0]?.answer(201, uploaded({ duplicate: { document_id: "doc-1", document_name: "Engagement letter", version_number: 2, archived: true } }));

    await user.click(await screen.findByRole("button", { name: "Upload anyway" }));
    await user.click(screen.getByRole("button", { name: "Add document" }));

    await vi.waitFor(() => expect(posted[0]?.body).toMatchObject({ allow_duplicate: true }));
  });

  it("puts a taken name on the name field", async () => {
    serve({
      create: () =>
        reply(409, { type: "/problems/document-name-taken", title: "x", status: 409, code: "document-name-taken", instance: "/x", request_id: "r" }),
    });
    wrap(<UploadPage department={FINANCE} />);
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Drop a PDF or Word file/), pdf());
    FakeUpload.sent[0]?.answer(201, uploaded());
    await user.click(await screen.findByRole("button", { name: "Add document" }));

    expect(await screen.findByText("Another document in this department already has this name")).toBeTruthy();
  });

  it("shows the server's reason on a refused file", async () => {
    serve({});
    wrap(<UploadPage department={FINANCE} />);
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Drop a PDF or Word file/), pdf("photo.pdf"));
    FakeUpload.sent[0]?.answer(415, { type: "/problems/unsupported-file", title: "Upload a PDF or Word (.docx) file", status: 415, code: "unsupported-file", instance: "/x", request_id: "r" });

    expect(await screen.findByText("Upload a PDF or Word (.docx) file")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("refuses a file over the limit before sending it", async () => {
    serve({});
    wrap(<UploadPage department={FINANCE} />);
    await screen.findByText(/up to 50 MB · up to 200 pages/);
    const big = pdf("Huge.pdf");
    Object.defineProperty(big, "size", { value: 51 * 1024 * 1024 });

    await userEvent.setup().upload(screen.getByLabelText(/Drop a PDF or Word file/), big);

    expect(await screen.findByText("Upload a file of 50 MB or less")).toBeTruthy();
    expect(FakeUpload.sent).toHaveLength(0);
  });

  it("states the limit the server enforces when it refuses a file as too large", async () => {
    META.document_max_bytes = 20 * 1024 * 1024;
    serve({});
    wrap(<UploadPage department={FINANCE} />);
    await screen.findByText(/up to 20 MB/);

    await userEvent.setup().upload(screen.getByLabelText(/Drop a PDF or Word file/), pdf());
    FakeUpload.sent[0]?.answer(413, { type: "/problems/payload-too-large", title: "The upload is too large", status: 413, code: "payload-too-large", instance: "/x", request_id: "r" });

    expect(await screen.findByText("Upload a file of 20 MB or less")).toBeTruthy();
  });

  it("treats a proxy's 502 as no answer, and offers to try again", async () => {
    serve({});
    wrap(<UploadPage department={FINANCE} />);
    await userEvent.setup().upload(await screen.findByLabelText(/Drop a PDF or Word file/), pdf());
    FakeUpload.sent[0]?.answer(502, null, {}, "Bad Gateway");

    expect(await screen.findByText("The upload didn't finish. Try again")).toBeTruthy();
    expect(screen.queryByText("Bad Gateway")).toBeNull();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("states how long to wait after too many uploads", async () => {
    serve({});
    wrap(<UploadPage department={FINANCE} />);
    await userEvent.setup().upload(await screen.findByLabelText(/Drop a PDF or Word file/), pdf());
    FakeUpload.sent[0]?.answer(
      429,
      { type: "/problems/rate-limited", title: "Too many attempts; try again later", status: 429, code: "rate-limited", instance: "/x", request_id: "r" },
      { "Retry-After": "600" },
    );

    expect(await screen.findByText("Too many attempts. Try again in 10 minutes.")).toBeTruthy();
  });

  it("sends an expired upload again on Try again, keeping the typed name", async () => {
    serve({
      create: () =>
        reply(404, { type: "/problems/upload-not-found", title: "This upload has expired. Upload the file again", status: 404, code: "upload-not-found", instance: "/x", request_id: "r" }),
    });
    wrap(<UploadPage department={FINANCE} />);
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Drop a PDF or Word file/), pdf());
    FakeUpload.sent[0]?.answer(201, uploaded());
    const name = await screen.findByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Client letter");
    await user.click(screen.getByRole("button", { name: "Add document" }));

    expect(await screen.findByText("This upload has expired. Upload the file again")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
    FakeUpload.sent[1]?.answer(201, uploaded({ id: "up-2" }));

    expect(((await screen.findByLabelText("Name")) as HTMLInputElement).value).toBe("Client letter");
  });

  it("explains instead of uploading in an archived department, and sends nothing handed over", async () => {
    serve({});
    handOff("d-1", [pdf("Handed over.pdf")]);
    wrap(<UploadPage department={{ ...FINANCE, status: "archived" }} />);
    expect(screen.getByText("This department is archived. Restore it to add documents.")).toBeTruthy();
    expect(screen.queryByLabelText(/Drop a PDF or Word file/)).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(FakeUpload.sent).toHaveLength(0);
  });

  it("stops an upload when its row is cancelled, and every upload when the page is left", async () => {
    serve({});
    const { unmount } = render(
      <QueryClientProvider client={makeQueryClient()}>
        <UploadPage department={FINANCE} />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Drop a PDF or Word file/), pdf("One.pdf"));
    await user.upload(screen.getByLabelText(/Drop a PDF or Word file/), pdf("Two.pdf"));

    await user.click(screen.getAllByRole("button", { name: "Cancel" })[0] as HTMLElement);
    expect(FakeUpload.sent[0]?.aborted).toBe(true);
    expect(screen.queryByText("One.pdf")).toBeNull();
    expect(FakeUpload.sent[1]?.aborted).toBe(false);

    unmount();
    expect(FakeUpload.sent[1]?.aborted).toBe(true);
  });
});
