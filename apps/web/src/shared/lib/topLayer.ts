"use client";

import { useSyncExternalStore } from "react";

const noSubscription = () => () => {};
const browserHasPopover = () => "showPopover" in HTMLElement.prototype;

/**
 * Whether what opens over the page (a dropdown's list, a tooltip) can be put in the browser's top
 * layer, as a manual popover: there no scrolling panel or dialog clips it. Known only in the
 * browser (not on the server, nor in every test DOM): until then it is drawn in place.
 */
export function useTopLayer(): boolean {
  return useSyncExternalStore(noSubscription, browserHasPopover, () => false);
}

/**
 * Whether an element is shown in the top layer: a modal dialog or an open popover. It sits over
 * the page, not in it, so what scrolls around its place in the document does not hold it.
 */
export function inTopLayer(element: Element): boolean {
  return element.matches(browserHasPopover() ? ":modal, :popover-open" : ":modal");
}
