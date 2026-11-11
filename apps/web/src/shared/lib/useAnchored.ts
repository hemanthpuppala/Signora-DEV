"use client";

import { useLayoutEffect, useState, type CSSProperties, type RefObject } from "react";

const GAP = 6;
const EDGE = 16;

/**
 * Where something that opens from a trigger goes (a dropdown's list, a calendar): under it, or
 * above when there is more room there, inside the visible part of the window (less than the window
 * while a phone's keyboard is up), following scrolls and resizes. In the top layer as a manual
 * popover when the browser has one, so no scrolling panel or dialog clips it.
 */
export function useAnchored(
  open: boolean,
  trigger: RefObject<HTMLElement | null>,
  floating: RefObject<HTMLElement | null>,
  { canPop, maxHeight }: { canPop: boolean; maxHeight: number },
): CSSProperties {
  const [place, setPlace] = useState<CSSProperties>({});
  useLayoutEffect(() => {
    const element = floating.current;
    if (!open || !element) return undefined;
    if (canPop && !element.matches(":popover-open")) element.showPopover();
    const follow = () => {
      const anchor = trigger.current;
      if (!anchor) return;
      const at = anchor.getBoundingClientRect();
      const view = window.visualViewport;
      const top = view?.offsetTop ?? 0;
      const bottom = top + (view?.height ?? window.innerHeight);
      const below = bottom - at.bottom - GAP - EDGE;
      const above = at.top - top - GAP - EDGE;
      const wanted = Math.min(element.scrollHeight, maxHeight);
      const up = below < wanted && above > below;
      const width = Math.max(at.width, element.offsetWidth);
      setPlace({
        left: Math.max(EDGE, Math.min(at.left, window.innerWidth - width - EDGE)),
        minWidth: at.width,
        maxHeight: Math.max(120, Math.min(maxHeight, up ? above : below)),
        ...(up ? { bottom: window.innerHeight - at.top + GAP } : { top: at.bottom + GAP }),
      });
    };
    follow();
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    window.visualViewport?.addEventListener("resize", follow);
    return () => {
      window.removeEventListener("scroll", follow, true);
      window.removeEventListener("resize", follow);
      window.visualViewport?.removeEventListener("resize", follow);
      if (canPop && element.matches(":popover-open")) element.hidePopover();
    };
  }, [open, canPop, trigger, floating, maxHeight]);
  return place;
}
