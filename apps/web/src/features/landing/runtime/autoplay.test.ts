import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAutoplay, IDLE_MS } from "./autoplay";
import { Scope } from "./scope";

/** Stands in for the browser's visibility reports; `show(true)` scrolls the demo into view. */
function installVisibility() {
  let report: (visible: boolean) => void = () => {};
  class Observer {
    constructor(callback: (entries: IntersectionObserverEntry[]) => void) {
      report = (visible) => callback([{ isIntersecting: visible } as IntersectionObserverEntry]);
    }
    observe(): void {}
    disconnect(): void {}
  }
  vi.stubGlobal("IntersectionObserver", Observer);
  return { show: (visible: boolean) => report(visible) };
}

describe("createAutoplay", () => {
  let scope: Scope;
  let passes: number;
  let resume: HTMLButtonElement;
  let visibility: ReturnType<typeof installVisibility>;

  /** A demo whose pass takes one second. */
  function demo(reduced = false) {
    return createAutoplay({
      scope,
      reduced,
      watch: document.createElement("div"),
      resume,
      play: async (alive) => {
        passes++;
        await scope.sleep(1000);
        return alive();
      },
    });
  }

  beforeEach(() => {
    vi.useFakeTimers();
    scope = new Scope();
    passes = 0;
    resume = document.createElement("button");
    resume.hidden = true;
    visibility = installVisibility();
  });
  afterEach(() => {
    scope.dispose();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("plays only while in view, and loops", async () => {
    const autoplay = demo();
    expect(autoplay.isOn()).toBe(false);
    visibility.show(true);
    expect(passes).toBe(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(passes).toBe(3);
    visibility.show(false);
    await vi.advanceTimersByTimeAsync(5000);
    expect(autoplay.isOn()).toBe(false);
    expect(passes).toBe(3);
  });

  it("hands over on interaction, shows Resume, and resumes after the idle time", async () => {
    const autoplay = demo();
    visibility.show(true);
    autoplay.takeOver();
    expect(autoplay.isOn()).toBe(false);
    expect(resume.hidden).toBe(false);
    await vi.advanceTimersByTimeAsync(IDLE_MS - 1);
    expect(passes).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(autoplay.isOn()).toBe(true);
    expect(resume.hidden).toBe(true);
    expect(passes).toBe(2);
  });

  it("restarts the idle time on every interaction and resumes at once on Resume", async () => {
    const autoplay = demo();
    visibility.show(true);
    autoplay.takeOver();
    await vi.advanceTimersByTimeAsync(IDLE_MS - 1000);
    autoplay.takeOver();
    await vi.advanceTimersByTimeAsync(IDLE_MS - 1000);
    expect(autoplay.isOn()).toBe(false);
    resume.click();
    expect(autoplay.isOn()).toBe(true);
  });

  it("stays with the visitor when scrolled away and back before the idle time", async () => {
    const autoplay = demo();
    visibility.show(true);
    autoplay.takeOver();
    visibility.show(false);
    visibility.show(true);
    expect(autoplay.isOn()).toBe(false);
  });

  it("never plays under reduced motion", () => {
    const autoplay = demo(true);
    visibility.show(true);
    expect(autoplay.isOn()).toBe(false);
    expect(passes).toBe(0);
  });

  it("stops for good when the page is left", async () => {
    demo();
    visibility.show(true);
    scope.dispose();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(passes).toBe(1);
  });
});
