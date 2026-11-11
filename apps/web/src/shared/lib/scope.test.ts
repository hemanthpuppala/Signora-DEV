import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Scope } from "./scope";

describe("Scope", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("stops its timers and listeners on dispose", () => {
    const scope = new Scope();
    const target = new EventTarget();
    const fired = vi.fn();
    scope.timeout(fired, 100);
    scope.on(target, "ping", fired);

    scope.dispose();
    vi.advanceTimersByTime(1000);
    target.dispatchEvent(new Event("ping"));
    expect(fired).not.toHaveBeenCalled();
  });

  it("registers nothing once disposed", () => {
    const scope = new Scope();
    scope.dispose();
    const target = new EventTarget();
    const fired = vi.fn();
    scope.timeout(fired, 100);
    scope.on(target, "ping", fired);

    vi.advanceTimersByTime(1000);
    target.dispatchEvent(new Event("ping"));
    expect(fired).not.toHaveBeenCalled();
  });

  it("clears a single timer without touching the others", () => {
    const scope = new Scope();
    const first = vi.fn();
    const second = vi.fn();
    scope.clearTimeout(scope.timeout(first, 100));
    scope.timeout(second, 100);

    vi.advanceTimersByTime(100);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
  });
});
