"use client";

import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { TextButton } from "../Button";
import styles from "./pdf.module.css";
import {
  canvasSize,
  clampZoom,
  cssSize,
  fitScale,
  pageAt,
  focusTop,
  pageOffsets,
  stepZoom,
  wheelFactor,
  type PageSize,
  type Rect,
} from "./view";

/** Re-render pages sharp once a zoom gesture has paused this long (ms); meanwhile the existing
 * bitmaps are scaled by CSS, so pages never blank. */
const RERENDER_AFTER = 150;
/** Pages within this distance of the viewport are rendered; farther ones are released. */
const RENDER_MARGIN = "100% 0px";

export type PdfOverlayArgs = {
  /** 1-based page number. */
  page: number;
  /** The live CSS scale: multiply PDF points by it to place things on the painted page. */
  scale: number;
};

export type PdfViewerProps = {
  /** The working copy's URL (same origin; loaded by byte ranges). */
  url: string;
  /** Page sizes in PDF points, rotation applied (the API's page facts): the layout is ready
   * before the file loads. */
  pages: readonly PageSize[];
  /** Accessible name, e.g. "Engagement letter, version 2". */
  label: string;
  /** Drawn over each page, in a box the size of the painted page (field review, signing). */
  renderOverlay?: (args: PdfOverlayArgs) => ReactNode;
  /** A box to bring into the middle of the view (a field chosen in a list); a new ``token``
   * scrolls to it again. */
  focus?: { page: number; rect: Rect; token: number } | null;
  /** Tools for the overlay, at the start of the toolbar (field review's palette). */
  tools?: ReactNode;
};

/**
 * The one PDF viewer (Phase 4 LLD topic 5), modelled on ScoutBoard's résumé builder: pages painted
 * on canvases by pdf.js, an overlay slot per page, fit to width, zoom (buttons, Ctrl or ⌘ with the
 * wheel, trackpad pinch) and page navigation. Only pages near the viewport are rendered, so 200
 * pages stay light. pdf.js is loaded on first use, never with the page bundle.
 */
export function PdfViewer({ url, pages, label, renderOverlay, focus, tools }: PdfViewerProps) {
  const paneRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [paneWidth, setPaneWidth] = useState(0);
  const [zoom, setZoom] = useState<number | "fit">("fit");
  // Keyed by URL, so a new URL shows nothing stale while it loads.
  const [loaded, setLoaded] = useState<{ url: string; document: PDFDocumentProxy } | null>(null);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const document = loaded?.url === url ? loaded.document : null;
  const failed = failedUrl === url;
  const [near, setNear] = useState<ReadonlySet<number>>(() => new Set());
  const [currentPage, setCurrentPage] = useState(1);

  const scale = useMemo(
    () => (zoom === "fit" ? fitScale(paneWidth, pages) : clampZoom(zoom)),
    [zoom, paneWidth, pages],
  );
  const [renderScale, setRenderScale] = useState(scale);
  useEffect(() => {
    if (renderScale === scale) return undefined;
    const timer = setTimeout(() => setRenderScale(scale), RERENDER_AFTER);
    return () => clearTimeout(timer);
  }, [scale, renderScale]);
  const offsets = useMemo(() => pageOffsets(pages, scale), [pages, scale]);

  // Keep the reading position when the scale changes.
  const previousScale = useRef(scale);
  useLayoutEffect(() => {
    const pane = paneRef.current;
    const before = previousScale.current;
    previousScale.current = scale;
    if (!pane || before === scale || before <= 0) return;
    pane.scrollTop = (pane.scrollTop + pane.clientHeight / 2) * (scale / before) - pane.clientHeight / 2;
  }, [scale]);

  useEffect(() => {
    const pane = paneRef.current;
    if (!pane) return undefined;
    setPaneWidth(pane.clientWidth);
    const observer = new ResizeObserver(([entry]) => setPaneWidth(entry?.contentRect.width ?? 0));
    observer.observe(pane);
    return () => observer.disconnect();
  }, []);

  // Load the document (pdf.js fetches it by ranges, so the first pages arrive quickly).
  useEffect(() => {
    let cancelled = false;
    let task: PDFDocumentLoadingTask | null = null;
    import("pdfjs-dist")
      .then((pdfjs) => {
        // Left (or switched files) before pdf.js arrived: open nothing, so nothing is left open.
        if (cancelled) return null;
        const base = `/pdfjs/${pdfjs.version}`;
        pdfjs.GlobalWorkerOptions.workerSrc = `${base}/pdf.worker.min.mjs`;
        task = pdfjs.getDocument({
          url,
          withCredentials: true,
          disableAutoFetch: true, // only the ranges the visible pages need
          enableXfa: false,
          wasmUrl: `${base}/wasm/`,
          standardFontDataUrl: `${base}/standard_fonts/`,
          cMapUrl: `${base}/cmaps/`,
          iccUrl: `${base}/iccs/`,
        });
        return task.promise;
      })
      .then((opened) => {
        if (opened && !cancelled) setLoaded({ url, document: opened });
      })
      .catch(() => {
        if (!cancelled) setFailedUrl(url);
      });
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [url]);

  // Which pages are near the viewport.
  useEffect(() => {
    const pane = paneRef.current;
    if (!pane) return undefined;
    const observer = new IntersectionObserver(
      (entries) =>
        setNear((previous) => {
          const next = new Set(previous);
          for (const entry of entries) {
            const page = Number((entry.target as HTMLElement).dataset.page);
            if (entry.isIntersecting) next.add(page);
            else next.delete(page);
          }
          return next;
        }),
      { root: pane, rootMargin: RENDER_MARGIN },
    );
    for (const element of pageRefs.current) if (element) observer.observe(element);
    return () => observer.disconnect();
  }, [pages.length]);

  const onScroll = useCallback(() => {
    const pane = paneRef.current;
    if (pane) setCurrentPage(pageAt(offsets, pane.scrollTop, pane.clientHeight));
  }, [offsets]);

  // Ctrl or ⌘ with the wheel (trackpad pinch arrives the same way) zooms the document, not the page.
  const scaleRef = useRef(scale);
  useLayoutEffect(() => {
    scaleRef.current = scale;
  }, [scale]);
  useEffect(() => {
    const pane = paneRef.current;
    if (!pane) return undefined;
    const onWheel = (event: WheelEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      event.preventDefault();
      setZoom(clampZoom(scaleRef.current * wheelFactor(event.deltaY)));
    };
    pane.addEventListener("wheel", onWheel, { passive: false });
    return () => pane.removeEventListener("wheel", onWheel);
  }, []);

  // Bring a chosen box into view (Phase 5 §6.2: a field picked in the list). Only a new pick (a
  // new ``token``) scrolls: the caller may build the focus afresh on every render, and a poll or
  // any other render must not pull the reader back. The box and the live layout are read through
  // refs, so zooming afterwards keeps the reader's place.
  const offsetsRef = useRef(offsets);
  const focusRef = useRef(focus);
  useLayoutEffect(() => {
    offsetsRef.current = offsets;
    focusRef.current = focus;
  });
  const focusToken = focus?.token;
  useEffect(() => {
    const pane = paneRef.current;
    const box = focusRef.current;
    if (!pane || !box || focusToken === undefined) return;
    const top = focusTop(offsetsRef.current, box.page, box.rect, scaleRef.current, pane.clientHeight);
    pane.scrollTo({ top, behavior: "smooth" });
  }, [focusToken]);

  const goTo = (page: number) => {
    const pane = paneRef.current;
    const top = offsets[page - 1];
    if (pane && top !== undefined) pane.scrollTo({ top, behavior: "smooth" });
  };

  const total = pages.length;
  return (
    <div className={styles.viewer}>
      <div className={styles.toolbar}>
        {tools ? <div className={styles.group}>{tools}</div> : null}
        <div className={styles.group}>
          <TextButton disabled={currentPage <= 1} onClick={() => goTo(currentPage - 1)}>
            Previous
          </TextButton>
          <span className={styles.readout} aria-live="polite">
            Page {currentPage} of {total}
          </span>
          <TextButton disabled={currentPage >= total} onClick={() => goTo(currentPage + 1)}>
            Next
          </TextButton>
        </div>
        <div className={styles.group}>
          <TextButton aria-label="Zoom out" onClick={() => setZoom(stepZoom(scale, -1))}>
            −
          </TextButton>
          <span className={styles.readout}>{Math.round(scale * 100)}%</span>
          <TextButton aria-label="Zoom in" onClick={() => setZoom(stepZoom(scale, 1))}>
            +
          </TextButton>
          {/* "Fit" keeps the toolbar on one line on a phone; its name says what it fits to. */}
          <TextButton aria-label="Fit width" disabled={zoom === "fit"} onClick={() => setZoom("fit")}>
            Fit
          </TextButton>
        </div>
      </div>
      <div
        ref={paneRef}
        className={styles.pane}
        role="region"
        aria-label={label}
        tabIndex={0}
        onScroll={onScroll}
      >
        {failed ? (
          <p className={styles.message}>This document couldn&apos;t be shown. Download the original instead.</p>
        ) : (
          <div className={styles.column}>
            {pages.map((page, index) => {
              const number = index + 1;
              const size = cssSize(page, scale);
              return (
                <div
                  key={number}
                  ref={(element) => {
                    pageRefs.current[index] = element;
                  }}
                  data-page={number}
                  className={styles.page}
                  style={{ width: size.width, height: size.height }}
                  role="img"
                  aria-label={`Page ${number} of ${total}`}
                >
                  <PageCanvas
                    document={document}
                    number={number}
                    page={page}
                    renderScale={renderScale}
                    active={near.has(number)}
                  />
                  {renderOverlay ? (
                    <div className={styles.overlay}>{renderOverlay({ page: number, scale })}</div>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/** One page's canvas: rendered off-screen and then shown, so a re-render never blanks it; released
 * (emptied) when it leaves the neighbourhood of the viewport, so memory stays bounded, and while a
 * new file loads, so no page of the previous one stays on screen. */
function PageCanvas({
  document,
  number,
  page,
  renderScale,
  active,
}: {
  document: PDFDocumentProxy | null;
  number: number;
  page: PageSize;
  renderScale: number;
  active: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    if (!active || !document) {
      canvas.width = 0; // release the bitmap
      canvas.height = 0;
      return undefined;
    }
    let cancelled = false;
    let task: RenderTask | null = null;
    const pixelRatio = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
    const target = canvasSize(page, renderScale, pixelRatio);
    document
      .getPage(number)
      .then((proxy) => {
        if (cancelled) return undefined;
        const offscreen = globalThis.document.createElement("canvas");
        offscreen.width = target.width;
        offscreen.height = target.height;
        task = proxy.render({ canvas: offscreen, viewport: proxy.getViewport({ scale: target.renderScale }) });
        return task.promise.then(() => {
          if (cancelled) return;
          canvas.width = target.width;
          canvas.height = target.height;
          canvas.getContext("2d")?.drawImage(offscreen, 0, 0);
        });
      })
      .catch(() => {
        // A cancelled render (scrolled away, zoomed again) is expected; a failed page stays blank.
      });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [document, number, page, renderScale, active]);

  return <canvas ref={canvasRef} className={styles.canvas} aria-hidden="true" />;
}
