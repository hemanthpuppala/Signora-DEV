import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { latchWheel } from "./scrollLatch";

/** A list that scrolls inside itself: 500 px of rows in a 100 px box (the test DOM lays nothing out). */
function scrollingList(): HTMLElement {
  const list = document.createElement("div");
  list.style.overflowY = "auto";
  Object.defineProperty(list, "scrollHeight", { value: 500 });
  Object.defineProperty(list, "clientHeight", { value: 100 });
  list.scrollBy = vi.fn() as unknown as HTMLElement["scrollBy"];
  document.body.append(list);
  return list;
}

function wheel(target: EventTarget, deltaY: number, at: number): WheelEvent {
  const event = new WheelEvent("wheel", { deltaY, bubbles: true, cancelable: true });
  Object.defineProperty(event, "timeStamp", { value: at });
  target.dispatchEvent(event);
  return event;
}

describe("a wheel gesture stays with what it started on", () => {
  let remove: () => void;
  let page: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    page = vi.fn();
    window.scrollBy = page as unknown as typeof window.scrollBy;
    remove = latchWheel();
  });
  afterEach(() => {
    remove();
    document.body.innerHTML = "";
  });

  it("started on the page, a list sliding under the pointer never takes it over", () => {
    const list = scrollingList();
    expect(wheel(document.body, 40, 1000).defaultPrevented).toBe(false); // the page scrolls
    const over = wheel(list, 40, 1050); // same gesture, now over the list
    expect(over.defaultPrevented).toBe(true);
    expect(page).toHaveBeenCalledWith({ top: 40 }); // the page keeps the gesture
  });

  it("started inside a list, the list scrolls; at its end the page carries on", () => {
    const list = scrollingList();
    expect(wheel(list, 40, 1000).defaultPrevented).toBe(false); // the list scrolls
    list.scrollTop = 400; // its end
    expect(wheel(list, 40, 1050).defaultPrevented).toBe(false); // the browser hands it to the page
    expect(wheel(document.body, 40, 1100).defaultPrevented).toBe(false);
  });

  it("a pause starts a new gesture", () => {
    const list = scrollingList();
    wheel(document.body, 40, 1000);
    expect(wheel(list, 40, 1500).defaultPrevented).toBe(false); // a new gesture, begun on the list
  });
});
