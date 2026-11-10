/**
 * Scroll latching (the platform behaviour of macOS and of most native apps, done once for the
 * console): a wheel gesture stays with what it started on. Started inside a scrolling list, the
 * list scrolls and, at its end, the page carries on (inside to outside). Started on the page, the
 * page scrolls, and a list that slides under the pointer meanwhile never takes the gesture over,
 * not even once the page has reached its end (never outside to inside). A pause ends a gesture.
 */

const GESTURE_GAP_MS = 200; // wheel events closer than this are one gesture
const LINE_PX = 16;

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
  const onWheel = (event: WheelEvent) => {
    if (event.ctrlKey) return; // a pinch or ctrl+wheel zooms
    if (event.timeStamp - last > GESTURE_GAP_MS) latched = null;
    last = event.timeStamp;
    if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return; // sideways: left alone
    const here = scrollerFor(event.target, event.deltaY);
    if (latched === null || latched === here) {
      latched = here;
      return;
    }
    if (contains(here, latched)) {
      latched = here; // the inner one reached its end: the outer carries on
      return;
    }
    // Latched outside, now over something inside: the gesture stays outside.
    event.preventDefault();
    const scale = event.deltaMode === 1 ? LINE_PX : event.deltaMode === 2 ? window.innerHeight : 1;
    latched.scrollBy({ top: event.deltaY * scale });
  };
  window.addEventListener("wheel", onWheel, { passive: false, capture: true });
  return () => window.removeEventListener("wheel", onWheel, { capture: true });
}
