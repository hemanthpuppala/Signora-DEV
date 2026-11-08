/**
 * Pure layout maths for the PDF viewer (Phase 4 LLD topic 5), apart from pdf.js so it is tested on
 * its own. Modelled on ScoutBoard's résumé builder canvas.
 *
 * Scale model: page sizes are in PDF points (as the API reports them, rotation applied). The CSS
 * scale fits a page's width into the pane; each canvas renders at cssScale × devicePixelRatio so it
 * stays sharp on high-density screens, and CSS shows it at the CSS size.
 */

export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 4;
export const ZOOM_STEP = 0.25;
/** Space (px) kept around a page when fitting it to the pane. */
export const FIT_PADDING = 32;
/** The gap (px) between pages. */
export const PAGE_GAP = 16;

export type PageSize = { width: number; height: number };

export function clampZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) return 1;
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(zoom * 100) / 100));
}

/** The CSS scale that fits the widest page into the pane. */
export function fitScale(paneWidth: number, pages: readonly PageSize[]): number {
  const widest = Math.max(0, ...pages.map((page) => page.width));
  if (!(paneWidth > 0) || !(widest > 0)) return 1;
  return clampZoom((paneWidth - FIT_PADDING) / widest);
}

/** A zoom step from the current scale, landing on the next multiple of the step. */
export function stepZoom(scale: number, direction: 1 | -1): number {
  const steps = scale / ZOOM_STEP;
  const next = direction > 0 ? Math.floor(steps + 1e-6) + 1 : Math.ceil(steps - 1e-6) - 1;
  return clampZoom(next * ZOOM_STEP);
}

/** Ctrl or ⌘ with the wheel, and trackpad pinch: a multiplicative factor, gentle per event. */
export function wheelFactor(deltaY: number): number {
  return Math.min(1.5, Math.max(0.6, Math.exp(-deltaY * 0.0015)));
}

/** On-screen size (px) of a page at a CSS scale: the overlay and the canvas both use this. */
export function cssSize(page: PageSize, scale: number): PageSize {
  return { width: Math.round(page.width * scale), height: Math.round(page.height * scale) };
}

/** Canvas backing-store size and the pdf.js render scale for a CSS scale and pixel ratio. */
export function canvasSize(page: PageSize, scale: number, pixelRatio: number) {
  const renderScale = scale * (pixelRatio > 0 ? pixelRatio : 1);
  return {
    width: Math.max(1, Math.round(page.width * renderScale)),
    height: Math.max(1, Math.round(page.height * renderScale)),
    renderScale,
  };
}

/** The top offset (px) of each page in the stacked column, gaps included. */
export function pageOffsets(pages: readonly PageSize[], scale: number): number[] {
  const offsets: number[] = [];
  let top = 0;
  for (const page of pages) {
    offsets.push(top);
    top += cssSize(page, scale).height + PAGE_GAP;
  }
  return offsets;
}

/** The 1-based page whose area covers the middle of the viewport. */
export function pageAt(offsets: readonly number[], scrollTop: number, viewportHeight: number): number {
  const middle = scrollTop + viewportHeight / 2;
  let page = 1;
  for (let index = 0; index < offsets.length; index += 1) {
    if ((offsets[index] ?? 0) <= middle) page = index + 1;
    else break;
  }
  return page;
}
