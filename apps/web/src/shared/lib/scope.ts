/**
 * Everything a landing demo starts (listeners, timers, animation frames, observers) is registered
 * here, so leaving the page stops all of it with one call.
 */
export class Scope {
  /** True once disposed; a running demo checks it between steps. */
  dead = false;
  private readonly disposers: Array<() => void> = [];
  private readonly timers = new Set<number>();
  private readonly frames = new Set<number>();

  on<E extends Event = Event>(
    target: EventTarget,
    type: string,
    handler: (event: E) => void,
    options?: AddEventListenerOptions | boolean,
  ): void {
    const listener = handler as EventListener;
    target.addEventListener(type, listener, options);
    this.disposers.push(() => target.removeEventListener(type, listener, options));
  }

  timeout(fn: () => void, ms: number): number {
    const id = window.setTimeout(() => {
      this.timers.delete(id);
      fn();
    }, ms);
    this.timers.add(id);
    return id;
  }

  clearTimeout(id: number): void {
    window.clearTimeout(id);
    this.timers.delete(id);
  }

  frame(fn: (now: number) => void): number {
    const id = window.requestAnimationFrame((now) => {
      this.frames.delete(id);
      fn(now);
    });
    this.frames.add(id);
    return id;
  }

  cancelFrame(id: number): void {
    window.cancelAnimationFrame(id);
    this.frames.delete(id);
  }

  /** Resolves after `ms`; never resolves once the scope is disposed. */
  sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      this.timeout(resolve, ms);
    });
  }

  /** Reports whether any part of `element` is in the viewport, now and whenever that changes. */
  whenVisible(element: Element, report: (visible: boolean) => void): void {
    const observer = new IntersectionObserver(
      (entries) => {
        const latest = entries[entries.length - 1];
        if (latest) report(latest.isIntersecting);
      },
      { threshold: 0 },
    );
    observer.observe(element);
    this.disposers.push(() => observer.disconnect());
  }

  /** Runs `handler` once the window has stopped resizing. */
  onResize(handler: () => void, settleMs = 150): void {
    let timer = 0;
    this.on(window, "resize", () => {
      this.clearTimeout(timer);
      timer = this.timeout(handler, settleMs);
    });
  }

  /** Registers extra clean-up to run on dispose. */
  add(disposer: () => void): void {
    this.disposers.push(disposer);
  }

  dispose(): void {
    if (this.dead) return;
    this.dead = true;
    this.timers.forEach((id) => window.clearTimeout(id));
    this.frames.forEach((id) => window.cancelAnimationFrame(id));
    this.timers.clear();
    this.frames.clear();
    while (this.disposers.length) this.disposers.pop()?.();
  }
}
