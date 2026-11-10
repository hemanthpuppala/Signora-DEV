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
