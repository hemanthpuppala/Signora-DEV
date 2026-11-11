"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import styles from "./tooltip.module.css";

/**
 * A "?" beside a title that explains it and its controls in a few lines. It opens on hover, on
 * click or tap (phones have no hover) and stays open while the pointer is over it; Escape or a
 * press elsewhere closes it. The words are real content: the button says it expands them, and a
 * screen reader reads them when open (unlike Tooltip, which only repeats a name).
 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false); // opened by a click: stays until closed
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) {
        setOpen(false);
        setPinned(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  return (
    <span
      ref={root}
      className={styles.info}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => {
        if (!pinned) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.stopPropagation();
          setOpen(false);
          setPinned(false);
        }
      }}
    >
      <button
        type="button"
        className={styles.infoButton}
        aria-label={`About ${label}`}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => {
          const next = !(open && pinned);
          setOpen(next);
          setPinned(next);
        }}
      >
        ?
      </button>
      {open ? (
        <span id={id} role="note" className={styles.infoTip}>
          {children}
        </span>
      ) : null}
    </span>
  );
}
