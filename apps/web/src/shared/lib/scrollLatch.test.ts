import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { latchWheel } from "./scrollLatch";

/** A list that scrolls inside itself: 500 px of rows in a 100 px box (the test DOM lays nothing out). */
function scrollingList(): HTMLElement & { scrollBy: ReturnType<typeof vi.fn> } {
  const list = document.createElement("div");
  list.style.overflowY = "auto";
  Object.defineProperty(list, "scrollHeight", { value: 500 });
  Object.defineProperty(list, "clientHeight", { value: 100 });
  list.scrollBy = vi.fn() as unknown as HTMLElement["scrollBy"];
  document.body.append(list);
  return list as unknown as HTMLElement & { scrollBy: ReturnType<typeof vi.fn> };
}

function wheel(target: EventTarget, deltaY: number, at: number, x = 10, y = 10, keys: WheelEventInit = {}): WheelEvent {
  const event = new WheelEvent("wheel", { deltaY, bubbles: true, cancelable: true, clientX: x, clientY: y, ...keys });
  Object.defineProperty(event, "timeStamp", { value: at });
  target.dispatchEvent(event);
  return event;
}

describe("a wheel gesture stays with what it began on, and stops at its end", () => {
  let remove: () => void;
  let page: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    page = vi.fn();
    window.scrollBy = page as unknown as typeof window.scrollBy;
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
    Object.defineProperty(document.documentElement, "scrollHeight", { value: 2000, configurable: true });
    window.scrollY = 0;
    remove = latchWheel();
  });
  afterEach(() => {
    remove();
    document.body.innerHTML = "";
  });

  it("begun on a list, the list scrolls; at its end the gesture stops; a new one moves the page", () => {
    const list = scrollingList();
    wheel(list, 40, 1000);
    expect(list.scrollBy).toHaveBeenLastCalledWith({ top: 40 });
    list.scrollTop = 400; // its end, mid-gesture
    wheel(list, 40, 1050);
    expect(list.scrollBy).toHaveBeenCalledTimes(1); // stopped: not handed to the page
    expect(page).not.toHaveBeenCalled();
    wheel(list, 40, 1500); // a new gesture, over the list at its end
    expect(page).toHaveBeenCalledWith({ top: 40 });
  });

  it("begun on the page, a list sliding under the pointer never takes it over", () => {
    const list = scrollingList();
    wheel(document.body, 40, 1000);
    wheel(list, 40, 1050);
    expect(page).toHaveBeenCalledTimes(2);
    expect(list.scrollBy).not.toHaveBeenCalled();
  });

  it.each([{ ctrlKey: true }, { metaKey: true }])("leaves a zoom alone: %o scrolls nothing", (keys) => {
    const list = scrollingList();
    const event = wheel(list, 40, 1000, 10, 10, keys);
    expect(list.scrollBy).not.toHaveBeenCalled();
    expect(page).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false); // the viewer under the pointer decides
  });

  it("leaves shift+wheel alone: the browser scrolls a wide table sideways", () => {
    // Browsers report it as an up-and-down delta with Shift held; taken as a scroll, the table
    // stayed where it was and the page moved instead.
    const list = scrollingList();
    const event = wheel(list, 40, 1000, 10, 10, { shiftKey: true });
    expect(list.scrollBy).not.toHaveBeenCalled();
    expect(page).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it("never moves the page while a modal dialog holds it still", () => {
    document.documentElement.style.overflowY = "hidden"; // globals.css: html:has(dialog:modal)
    try {
      const event = wheel(document.body, 40, 1000);
      expect(page).not.toHaveBeenCalled();
      expect(event.defaultPrevented).toBe(true); // nor does the browser move anything else
    } finally {
      document.documentElement.style.overflowY = "";
    }
  });

  it("what is shown over the page is not held by the areas behind it", () => {
    // A dialog opened from inside a scrolling column: a wheel over it is the page's, never the
    // column's, which is behind it.
    const column = scrollingList();
    const dialog = document.createElement("dialog");
    // The test DOM has no top layer: this dialog says it is a modal one.
    dialog.matches = ((selectors: string) => selectors.includes(":modal")) as HTMLDialogElement["matches"];
    column.append(dialog);
    wheel(dialog, 40, 1000);
    expect(column.scrollBy).not.toHaveBeenCalled();
    expect(page).toHaveBeenCalledWith({ top: 40 });
  });

  it("moving the pointer starts a new gesture; content sliding under a still pointer does not", () => {
    const list = scrollingList();
    wheel(document.body, 40, 1000, 10, 10);
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 10, clientY: 10 }));
    wheel(list, 40, 1050, 10, 10);
    expect(list.scrollBy).not.toHaveBeenCalled(); // still the page's gesture
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 300, clientY: 200 }));
    wheel(list, 40, 1100, 300, 200);
    expect(list.scrollBy).toHaveBeenCalledWith({ top: 40 }); // the list it was moved onto
  });
});
