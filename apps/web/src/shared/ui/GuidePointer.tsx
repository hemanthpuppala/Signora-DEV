"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { useTopLayer } from "@/shared/lib/topLayer";

import styles from "./guidePointer.module.css";

type Box = { left: number; top: number; width: number; height: number };

const RING = 4; // px around the field
const ROOM = 200; // px the label and arrow need beside the field

/**
 * The guide's pointer (Phase 8 §4.3): a soft ring around the field to fill and a curved arrow
 * beside it with what to do ("Fill Full name"), drawn in once (instantly with reduced motion). In
 * the top layer, following the field as the page scrolls or zooms, and never catching a click.
 * Announced to screen readers by the caller (the field takes focus); the pointer itself is visual.
 */
export function GuidePointer({ target, label }: { target: Element | null; label: string }) {
  const layer = useRef<HTMLDivElement>(null);
  const canPop = useTopLayer();
  const [box, setBox] = useState<Box | null>(null);

  useLayoutEffect(() => {
    const element = layer.current;
    if (!target || !element) return undefined;
    if (canPop && !element.matches(":popover-open")) element.showPopover();
    let frame = 0;
    const follow = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const at = target.getBoundingClientRect();
        setBox({ left: at.left, top: at.top, width: at.width, height: at.height });
      });
    };
    follow();
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    const resized = new ResizeObserver(follow);
    resized.observe(target);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", follow, true);
      window.removeEventListener("resize", follow);
      resized.disconnect();
      if (canPop && element.matches(":popover-open")) element.hidePopover();
    };
  }, [target, canPop]);

  const left = box !== null && box.left > ROOM; // room on the left: point from there; else from above
  return (
    <div ref={layer} className={styles.layer} popover={canPop ? "manual" : undefined} aria-hidden="true">
      {box ? (
        <>
          <div
            className={styles.ring}
            style={{ left: box.left - RING, top: box.top - RING, width: box.width + RING * 2, height: box.height + RING * 2 }}
          />
          <div
            key={label}
            className={styles.pointer}
            style={
              left
                ? { right: window.innerWidth - box.left + RING + 4, top: box.top + box.height / 2 - 14 }
                : { left: box.left, top: Math.max(4, box.top - RING - 40) }
            }
          >
            <span className={styles.label}>{label}</span>
            <svg className={`${styles.arrow} ${styles.draw}`} viewBox="0 0 44 28">
              {left ? <path d="M2 4 C 18 4, 30 8, 40 14 M33 9 L40 14 L33 19" /> : <path d="M4 2 C 4 14, 10 20, 22 26 M14 25 L22 26 L20 18" />}
            </svg>
          </div>
        </>
      ) : null}
    </div>
  );
}
