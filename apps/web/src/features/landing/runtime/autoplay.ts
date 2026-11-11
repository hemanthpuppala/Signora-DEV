import type { Scope } from "@/shared/lib/scope";

/** How long a demo the visitor took over stays theirs before it plays again by itself. */
export const IDLE_MS = 60_000;

type AutoplayOptions = {
  scope: Scope;
  /** The visitor asked for reduced motion: the demo never plays by itself. */
  reduced: boolean;
  /** The demo plays only while this element is in view. */
  watch: Element;
  /**
   * One pass of the demo. It checks `alive()` after every wait and resolves `false` as soon as that
   * turns false; resolving `true` plays the next pass.
   */
  play: (alive: () => boolean) => Promise<boolean>;
  /** The "Resume demo" button, for a demo the visitor can take over. */
  resume?: HTMLButtonElement;
  onStart?: () => void;
  onStop?: () => void;
};

export type Autoplay = {
  /** True while the demo is playing by itself. */
  isOn(): boolean;
  /** The visitor touched the demo: stop playing, show Resume, and play again after the idle time. */
  takeOver(): void;
  /** Starts the current pass again from the top (after a layout change), if the demo is playing. */
  restart(): void;
};

/**
 * The rules every self-playing demo on the page follows: it plays only while in view, any
 * interaction hands it to the visitor (with a Resume button), and it resumes from the start after
 * `IDLE_MS` without interaction or when Resume is pressed.
 */
export function createAutoplay(options: AutoplayOptions): Autoplay {
  const { scope, reduced, watch, play, resume, onStart, onStop } = options;
  let on = false;
  let taken = false;
  let visible = false;
  let run = 0;
  let idle = 0;

  async function loop(): Promise<void> {
    const id = ++run;
    const alive = () => on && id === run && !scope.dead;
    let again = true;
    while (again) again = await play(alive);
  }

  function start(): void {
    if (on || taken || reduced) return;
    if (resume) resume.hidden = true;
    onStart?.();
    on = true;
    void loop();
  }

  function stop(): void {
    if (!on) return;
    on = false;
    run++;
    onStop?.();
  }

  function takeOver(): void {
    if (on) {
      taken = true;
      stop();
    }
    if (!taken) return;
    if (resume) resume.hidden = false;
    scope.clearTimeout(idle);
    idle = scope.timeout(() => {
      taken = false;
      if (visible) start();
    }, IDLE_MS);
  }

  scope.whenVisible(watch, (nowVisible) => {
    visible = nowVisible;
    if (nowVisible) start();
    else stop();
  });
  if (resume) {
    scope.on(resume, "click", () => {
      scope.clearTimeout(idle);
      taken = false;
      start();
    });
  }

  return {
    isOn: () => on,
    takeOver,
    restart: () => {
      if (on) void loop();
    },
  };
}
