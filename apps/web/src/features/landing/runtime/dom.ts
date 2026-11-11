import { context2d } from "@/shared/lib/canvas";

/** The element matching `selector`; the landing markup always has it, so a miss is a broken build. */
export function q<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  if (!element) throw new Error(`Landing page: no element matches "${selector}"`);
  return element;
}

export function qa<T extends Element = HTMLElement>(root: ParentNode, selector: string): T[] {
  return Array.from(root.querySelectorAll<T>(selector));
}

/** A design token's value on `element`. */
export function cssVar(element: Element, name: string): string {
  return getComputedStyle(element).getPropertyValue(name).trim();
}

export type Surface = { ctx: CanvasRenderingContext2D; w: number; h: number };

/** Sizes a canvas's bitmap to its box at the screen's pixel ratio; drawing then uses CSS pixels. */
export function sizeCanvas(canvas: HTMLCanvasElement): Surface {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = Math.max(1, Math.round(w * dpr));
  canvas.height = Math.max(1, Math.round(h * dpr));
  const ctx = context2d(canvas);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

/**
 * Shows a spinner and `label` on a button while its action runs; the returned call restores it.
 * Returns `null` when the button is already busy: the action is running and must not start again
 * (the busy style stops the pointer, but not Enter or Space).
 */
export function setBusy(button: HTMLButtonElement, label: string): (() => void) | null {
  if (button.classList.contains("is-busy")) return null;
  const original = Array.from(button.childNodes);
  const spinner = document.createElement("span");
  spinner.className = "spin";
  spinner.setAttribute("aria-hidden", "true");
  button.classList.add("is-busy");
  button.replaceChildren(spinner, label);
  return () => {
    button.classList.remove("is-busy");
    button.replaceChildren(...original);
  };
}

/** Marks a field valid or invalid with its message; returns whether it is valid. */
export function fieldError(input: HTMLInputElement, slot: HTMLElement, message: string): boolean {
  input.setAttribute("aria-invalid", message ? "true" : "false");
  slot.textContent = message;
  return !message;
}
