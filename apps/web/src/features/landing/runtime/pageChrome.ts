import { clamp } from "@/shared/lib/canvas";

import { SECTIONS } from "../content";

import { cssVar, q, qa, sizeCanvas } from "./dom";
import type { Scope } from "@/shared/lib/scope";

/** Display headlines drift sideways as they cross the viewport (a third of the distance on phones). */
function mountDrift(root: HTMLElement, scope: Scope, reduced: boolean): void {
  const lines = qa(root, "[data-drift]");
  let queued = 0;
  const drift = () => {
    queued = 0;
    const viewport = window.innerHeight || 800;
    const scale = window.innerWidth < 700 ? 0.3 : 1;
    for (const line of lines) {
      const box = line.getBoundingClientRect();
      const progress = clamp((box.top + box.height / 2 - viewport / 2) / viewport, -1, 1);
      const distance = Number(line.dataset.drift) * progress * scale;
      line.style.transform = reduced ? "" : `translateX(${distance.toFixed(1)}px)`;
    }
  };
  scope.on(
    window,
    "scroll",
    () => {
      if (!queued) queued = scope.frame(drift);
    },
    { passive: true },
  );
  scope.onResize(drift);
  drift();
}

/** The header underlines the link of the section that fills most of the viewport. */
function mountSectionNav(root: HTMLElement, scope: Scope): void {
  const links = qa<HTMLAnchorElement>(root, "#top-links a[data-sec]");
  const indicator = q(root, "#top-ind");
  const setActive = (id: string | null) => {
    let active: HTMLAnchorElement | null = null;
    for (const link of links) {
      const match = link.dataset.sec === id;
      link.setAttribute("aria-current", match ? "true" : "false");
      if (match) active = link;
    }
    if (active) {
      indicator.style.left = `${active.offsetLeft}px`;
      indicator.style.width = `${active.offsetWidth}px`;
      indicator.style.opacity = "1";
    } else {
      indicator.style.opacity = "0";
    }
  };
  const visible = new Map<string, number>();
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) visible.set(entry.target.id, entry.intersectionRatio);
      let best: string | null = null;
      let bestRatio = 0.15;
      for (const [id, ratio] of visible) {
        if (ratio > bestRatio) {
          bestRatio = ratio;
          best = id;
        }
      }
      setActive(best);
    },
    { threshold: [0, 0.15, 0.3, 0.5, 0.75, 1] },
  );
  for (const section of SECTIONS) observer.observe(q(root, `#${section.id}`));
  scope.add(() => observer.disconnect());
}

/** The phone menu: a bottom sheet that closes on a choice, the backdrop or Escape. */
function mountSheet(root: HTMLElement, scope: Scope, reduced: boolean): void {
  const sheet = q(root, "#sheet");
  const close = () => {
    if (sheet.hidden) return;
    sheet.classList.remove("is-open");
    scope.timeout(() => {
      sheet.hidden = true;
    }, reduced ? 0 : 360);
  };
  scope.on(q(root, "#menu-btn"), "click", () => {
    sheet.hidden = false;
    // Two frames, so the browser paints the closed state before the transition to open.
    scope.frame(() => scope.frame(() => sheet.classList.add("is-open")));
  });
  scope.on<MouseEvent>(sheet, "click", (event) => {
    const target = event.target as Element;
    if (target === sheet || target.closest("[data-sheet-close]")) close();
  });
  scope.on<KeyboardEvent>(sheet, "keydown", (event) => {
    if (event.key === "Escape") close();
  });
}

/** The halftone band above the footer: dots that grow toward the bottom edge. */
function mountBand(root: HTMLElement, scope: Scope): void {
  const band = q<HTMLCanvasElement>(root, "#band-canvas");
  const draw = () => {
    const { ctx, w, h } = sizeCanvas(band);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = cssVar(root, "--paper");
    const gap = 9;
    const maxRadius = gap * 0.62;
    for (let row = 0, y = gap / 2; y < h + gap; row++, y += gap * 0.866) {
      for (let x = row % 2 ? gap / 2 : 0; x < w + gap; x += gap) {
        const p = clamp((y / h) * 1.15 - 0.22 + 0.16 * Math.sin((x / w) * Math.PI * 2.2 + 0.8), 0, 1);
        const radius = maxRadius * p * p * (3 - 2 * p);
        if (radius >= 0.35) {
          ctx.beginPath();
          ctx.arc(x, y, radius, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  };
  draw();
  scope.onResize(draw);
}

/** The Templates headline rises out of its masks each time it scrolls into view. */
function mountMaskRise(root: HTMLElement, scope: Scope): void {
  const text = q(root, "#tpl-text");
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && entry.intersectionRatio > 0.55) text.classList.add("is-in");
        else if (!entry.isIntersecting) text.classList.remove("is-in");
      }
    },
    { threshold: [0, 0.55, 0.9] },
  );
  observer.observe(q(text, "h2"));
  scope.add(() => observer.disconnect());
}

export type Toast = (message: string) => void;

/** A short status line at the bottom of the page. */
export function createToast(root: HTMLElement, scope: Scope): Toast {
  const element = q(root, "#toast");
  let timer = 0;
  return (message) => {
    element.textContent = message;
    element.classList.add("is-on");
    scope.clearTimeout(timer);
    timer = scope.timeout(() => element.classList.remove("is-on"), 2200);
  };
}

export function mountPageChrome(root: HTMLElement, scope: Scope, reduced: boolean): void {
  mountDrift(root, scope, reduced);
  mountSectionNav(root, scope);
  mountSheet(root, scope, reduced);
  mountBand(root, scope);
  mountMaskRise(root, scope);
}
