/**
 * Scroll latching, as macOS, iOS and Chrome's touchpad scrolling do it, done once for the console:
 *
 * - A gesture begins on the innermost scroll area under the pointer that can still move that way
 *   (the PDF, a list, the details column), else the next one out, else the page. So when the area
 *   under the pointer is already at its end, a new gesture moves what holds it.
 * - The whole gesture stays with what it began on. At its end the scroll stops: it never passes to
 *   another area partway through (momentum included), and an area that slides under the pointer
 *   never takes it over.
 * - A gesture ends with a pause, or when the person moves the pointer. Content sliding under a
 *   still pointer is not a move.
 *
 * Only an up-and-down scroll is taken. A pinch or Ctrl/Cmd+wheel (the viewer's zoom), a sideways
 * gesture and Shift+wheel (the browser's sideways scroll of a wide table or a zoomed page) are
 * left to the browser. What is shown over the page (a modal dialog, an open list) is not held by
 * the areas behind it, and the page itself does not move while a modal dialog holds it still.
 */

import { inTopLayer } from "./topLayer";

const GESTURE_GAP_MS = 200; // wheel events closer than this are one gesture
const LINE_PX = 16;
const MOVED_PX = 4; // the pointer went somewhere: a new gesture

type Scroller = Element | Window;

const scrollsY = (el: Element) => {
  const overflow = getComputedStyle(el).overflowY;
  return (overflow === "auto" || overflow === "scroll") && el.scrollHeight > el.clientHeight + 1;
};

/** Whether ``scroller`` has room to move by ``deltaY``. */
export function canMove(scroller: Scroller, deltaY: number): boolean {
  if (scroller === window) {
    const page = document.documentElement;
    if (getComputedStyle(page).overflowY === "hidden") return false; // held still behind a modal dialog (globals.css)
    return deltaY > 0 ? window.scrollY + window.innerHeight < page.scrollHeight - 1 : window.scrollY > 0;
  }
  const el = scroller as Element;
  return deltaY > 0 ? el.scrollTop + el.clientHeight < el.scrollHeight - 1 : el.scrollTop > 0;
}

/** Where a gesture beginning on ``target`` goes: the innermost scroll area holding it with room to
 * move that way, else the page. The search stops at what is shown over the page. */
export function scrollerFor(target: EventTarget | null, deltaY: number): Scroller {
  for (let el = target instanceof Element ? target : null; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
    if (scrollsY(el) && canMove(el, deltaY)) return el;
    if (inTopLayer(el)) break; // over the page, not in it: the areas behind it never take its scroll
  }
  return window;
}

/** Installs the rule on the window; returns its removal. */
export function latchWheel(): () => void {
  let latched: Scroller | null = null;
  let last = -Infinity;
  let at = { x: 0, y: 0 }; // where the pointer was at the last wheel

  const onPointerMove = (event: PointerEvent) => {
    if (Math.hypot(event.clientX - at.x, event.clientY - at.y) > MOVED_PX) latched = null;
  };

  const onWheel = (event: WheelEvent) => {
    if (event.ctrlKey || event.metaKey) return; // a pinch, or ctrl/cmd+wheel: the viewer's zoom, never a scroll
    if (event.shiftKey) return; // shift+wheel: the browser's sideways scroll, reported as an up-and-down delta
    if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return; // sideways: left alone
    if (event.timeStamp - last > GESTURE_GAP_MS) latched = null;
    last = event.timeStamp;
    at = { x: event.clientX, y: event.clientY };
    if (latched === null) latched = scrollerFor(event.target, event.deltaY);
    // The scroll is always done here, on what the gesture began on: the browser's own chaining and
    // latching never decide where it goes.
    event.preventDefault();
    if (!canMove(latched, event.deltaY)) return; // at its end: the gesture stops there
    const scale = event.deltaMode === 1 ? LINE_PX : event.deltaMode === 2 ? window.innerHeight : 1;
    latched.scrollBy({ top: event.deltaY * scale });
  };

  window.addEventListener("wheel", onWheel, { passive: false, capture: true });
  window.addEventListener("pointermove", onPointerMove, { passive: true, capture: true });
  return () => {
    window.removeEventListener("wheel", onWheel, { capture: true });
    window.removeEventListener("pointermove", onPointerMove, { capture: true });
  };
}
