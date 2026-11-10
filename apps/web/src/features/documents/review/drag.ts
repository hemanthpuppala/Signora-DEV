/**
 * The maths of dragging a box over the pages (Phase 6 §5.1), apart from the DOM so it is tested on
 * its own: which page a dragged box lands on, and how fast the pages scroll under a drag held near
 * their edge.
 */

/** A page's place on screen: its number, and its top and bottom edges (px). */
export type Band = { page: number; top: number; bottom: number };

/** Pixels a press may wander before it is a drag: a finger is less steady than a mouse. */
export const slop = (pointerType: string): number => (pointerType === "touch" ? 8 : 3);

/**
 * The page a dragged box lands on: the one its middle is over, else the nearest (a box let go in
 * the gap between two pages). Its own page wins a tie, so a box never leaves by accident.
 */
export function landingPage(middle: number, own: number, bands: readonly Band[]): number {
  const away = (band: Band) => (middle < band.top ? band.top - middle : middle > band.bottom ? middle - band.bottom : 0);
  let best = bands.find((band) => band.page === own);
  for (const band of bands) {
    if (!best || away(band) < away(best)) best = band;
  }
  return best?.page ?? own;
}

const EDGE = 56; // px from the top or bottom of what scrolls where a held drag starts scrolling it
const FASTEST = 18; // px a frame, with the pointer at the very edge or past it

/**
 * How far to scroll this frame (px; negative is up) with the pointer at ``y`` inside what scrolls
 * from ``top`` to ``bottom``: nothing in the middle, faster the nearer the edge.
 */
export function edgeSpeed(y: number, top: number, bottom: number): number {
  if (bottom - top < EDGE * 3) return 0; // too short to have a middle
  const near = (distance: number) => Math.ceil(FASTEST * Math.min(1, Math.max(0, (EDGE - distance) / EDGE)));
  if (y < top + EDGE) return -near(y - top);
  if (y > bottom - EDGE) return near(bottom - y);
  return 0;
}

/** The nearest ancestor that scrolls up and down (the viewer's pane), if any. */
export function scrollParent(element: Element | null): HTMLElement | null {
  for (let node = element?.parentElement ?? null; node; node = node.parentElement) {
    const flow = getComputedStyle(node).overflowY;
    if (flow === "auto" || flow === "scroll") return node;
  }
  return null;
}
