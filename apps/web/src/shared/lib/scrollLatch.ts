/**
 * Scroll latching (the platform behaviour of macOS and of most native apps, done once for the
 * console): a wheel gesture stays with what it started on. Started inside a scrolling list, the
 * list scrolls and, at its end, the page carries on (inside to outside). Started on the page, the
 * page scrolls, and a list that slides under the pointer meanwhile never takes the gesture over,
 * not even once the page has reached its end (never outside to inside).
 *
 * A gesture ends with a pause, or when the person moves the pointer: what is under it then gets
 * the next wheel first (the PDF, when the pointer goes to it). Content sliding under a still
 * pointer is not a move: its position on the screen is unchanged.
 */

const GESTURE_GAP_MS = 200; // wheel events closer than this are one gesture
const LINE_PX = 16;
const MOVED_PX = 4; // the pointer went somewhere: a new gesture
// How long after a pointer move the browser may still send the wheel to what it scrolled before
// (its own latching outlasts our pause): until then the wheel is scrolled here.
const BROWSER_LATCH_MS = 1000;

type Scroller = Element | Window;

/** The innermost thing under ``target`` that this wheel would move: a scrolling box with room to
 * move that way (or one that keeps its scroll to itself), else the page. */
export function scrollerFor(target: EventTarget | null, deltaY: number): Scroller {
  for (let el = target instanceof Element ? target : null; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
    const style = getComputedStyle(el);
    if (!/(auto|scroll)/.test(style.overflowY) || el.scrollHeight <= el.clientHeight + 1) continue;
    const room = deltaY > 0 ? el.scrollTop + el.clientHeight < el.scrollHeight - 1 : el.scrollTop > 0;
    if (room || style.overscrollBehaviorY === "contain" || style.overscrollBehaviorY === "none") return el;
  }
  return window;
}

const contains = (outer: Scroller, inner: Scroller) =>
  outer === window || (inner !== window && (outer as Element).contains(inner as Element));

/** Installs the rule on the window; returns its removal. */
export function latchWheel(): () => void {
  let latched: Scroller | null = null;
  let last = -Infinity;
  let at = { x: 0, y: 0 }; // where the pointer was at the last wheel
  // After the pointer moves, the browser's own latching would keep sending the wheel to what it
  // scrolled before for a moment: until ``ownUntil`` the wheel is scrolled here, not by the browser.
  let ownUntil = -Infinity;
  const scale = (event: WheelEvent) =>
    event.deltaMode === 1 ? LINE_PX : event.deltaMode === 2 ? window.innerHeight : 1;
  const onPointerMove = (event: PointerEvent) => {
    if (Math.hypot(event.clientX - at.x, event.clientY - at.y) > MOVED_PX) {
      latched = null;
      ownUntil = event.timeStamp + BROWSER_LATCH_MS;
      at = { x: event.clientX, y: event.clientY };
    }
  };
  const onWheel = (event: WheelEvent) => {
    if (event.ctrlKey) return; // a pinch or ctrl+wheel zooms
    if (event.timeStamp - last > GESTURE_GAP_MS) latched = null;
    last = event.timeStamp;
    at = { x: event.clientX, y: event.clientY };
    if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return; // sideways: left alone
    const here = scrollerFor(event.target, event.deltaY);
    if (latched === null || latched === here || contains(here, latched)) {
      latched = here; // a new gesture, the same one, or an inner one at its end handing outward
      if (event.timeStamp < ownUntil) {
        event.preventDefault();
        latched.scrollBy({ top: event.deltaY * scale(event) });
      }
      return;
    }
    // Latched outside, now over something inside: the gesture stays outside.
    event.preventDefault();
    latched.scrollBy({ top: event.deltaY * scale(event) });
  };
  window.addEventListener("wheel", onWheel, { passive: false, capture: true });
  window.addEventListener("pointermove", onPointerMove, { passive: true, capture: true });
  return () => {
    window.removeEventListener("wheel", onWheel, { capture: true });
    window.removeEventListener("pointermove", onPointerMove, { capture: true });
  };
}
