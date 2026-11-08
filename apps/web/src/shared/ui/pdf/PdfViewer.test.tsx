import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PdfViewer } from "./PdfViewer";

const getDocument = vi.fn();
vi.mock("pdfjs-dist", () => ({
  version: "6.4.299",
  GlobalWorkerOptions: {} as { workerSrc?: string },
  getDocument: (options: unknown) => getDocument(options),
}));

const A4 = { width: 595, height: 842 };

function loads(succeeds = true) {
  getDocument.mockReturnValue({
    promise: succeeds
      ? Promise.resolve({ numPages: 2, getPage: vi.fn(() => new Promise(() => {})) })
      : Promise.reject(new Error("bad pdf")),
    destroy: vi.fn(),
  });
}

describe("PdfViewer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    getDocument.mockReset();
  });

  it("lays out every page from the page facts and loads the file by ranges from our origin", async () => {
    loads();
    render(<PdfViewer url="/api/v1/documents/d/versions/v/pdf" pages={[A4, A4, A4]} label="Letter, version 1" />);

    expect(screen.getByRole("region", { name: "Letter, version 1" })).toBeTruthy();
    expect(screen.getAllByRole("img").map((page) => page.getAttribute("aria-label"))).toEqual([
      "Page 1 of 3",
      "Page 2 of 3",
      "Page 3 of 3",
    ]);
    expect(screen.getByText("Page 1 of 3")).toBeTruthy();
    await vi.waitFor(() => expect(getDocument).toHaveBeenCalled());
    expect(getDocument.mock.calls[0]?.[0]).toMatchObject({
      url: "/api/v1/documents/d/versions/v/pdf",
      disableAutoFetch: true,
      enableXfa: false,
      wasmUrl: "/pdfjs/6.4.299/wasm/",
      standardFontDataUrl: "/pdfjs/6.4.299/standard_fonts/",
    });
  });

  it("zooms with the buttons and returns to fit width", async () => {
    loads();
    render(<PdfViewer url="/x.pdf" pages={[A4]} label="Letter" />);
    const user = userEvent.setup();
    const page = screen.getByRole("img", { name: "Page 1 of 1" });
    const fit = screen.getByRole("button", { name: "Fit width" }) as HTMLButtonElement;
    expect(fit.disabled).toBe(true);

    await user.click(screen.getByRole("button", { name: "Zoom in" }));

    expect(screen.getByText("125%")).toBeTruthy(); // jsdom has no width: fit is 100%
    expect(page.style.width).toBe(`${Math.round(595 * 1.25)}px`);
    expect(fit.disabled).toBe(false);
    await user.click(fit);
    expect(screen.getByText("100%")).toBeTruthy();
  });

  it("draws the overlay on every page at the live scale", () => {
    loads();
    render(
      <PdfViewer
        url="/x.pdf"
        pages={[A4, A4]}
        label="Letter"
        renderOverlay={({ page, scale }) => <span>{`field on ${page} at ${scale}`}</span>}
      />,
    );
    expect(screen.getByText("field on 1 at 1")).toBeTruthy();
    expect(screen.getByText("field on 2 at 1")).toBeTruthy();
  });

  it("opens nothing when it is left before pdf.js has arrived", async () => {
    loads();
    const { unmount } = render(<PdfViewer url="/x.pdf" pages={[A4]} label="Letter" />);
    unmount(); // pdf.js is imported on first use, so it has not arrived yet

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(getDocument).not.toHaveBeenCalled();
  });

  it("shows no page of the previous file while a new one loads", async () => {
    // Every page is in view, and painting succeeds (jsdom has no 2D context: the size shows it).
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(private readonly report: IntersectionObserverCallback) {}
        observe(target: Element) {
          this.report([{ target, isIntersecting: true } as IntersectionObserverEntry], this as never);
        }
        disconnect() {}
      },
    );
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const page = { getViewport: () => ({}), render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }) };
    getDocument.mockImplementation(({ url }: { url: string }) => ({
      promise: url === "/v2.pdf" ? Promise.resolve({ numPages: 1, getPage: () => Promise.resolve(page) }) : new Promise(() => {}),
      destroy: vi.fn(),
    }));
    const { container, rerender } = render(<PdfViewer url="/v2.pdf" pages={[A4]} label="Letter, version 2" />);
    const canvas = container.querySelector("canvas") as HTMLCanvasElement;
    await vi.waitFor(() => expect(canvas.width).toBeGreaterThan(0));

    rerender(<PdfViewer url="/v1.pdf" pages={[A4]} label="Letter, version 1" />);

    await vi.waitFor(() => expect(canvas.width).toBe(0));
  });

  it("says so when the document cannot be shown", async () => {
    loads(false);
    render(<PdfViewer url="/x.pdf" pages={[A4]} label="Letter" />);
    expect(await screen.findByText("This document couldn't be shown. Download the original instead.")).toBeTruthy();
  });
});
