"use client";

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { cx } from "@/shared/lib/cx";
import { useTopLayer } from "@/shared/lib/topLayer";

import { Icon, type IconName } from "./Icon";
import styles from "./tooltip.module.css";

const GAP = 6; // between the tip and what it names
const EDGE = 8; // the tip stays this far inside the window

/**
 * A short label shown above what it wraps, on hover and on keyboard focus; Escape hides it
 * (WCAG 1.4.13). It is visual only: what it wraps must carry the same words for assistive
 * technology (an icon button's name, or the text itself).
 *
 * The tip sits above everything (the browser's top layer, as a manual popover), so a scrolling
 * panel never clips it: centred over what it names, kept inside the window, and under it when
 * there is no room above. Scrolling hides it, since what it named has moved.
 */
export function Tooltip({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string | undefined;
}) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLSpanElement>(null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [place, setPlace] = useState<CSSProperties>({});
  const canPop = useTopLayer();
  const shown = (hovered || focused) && !dismissed;

  // Listened for on the element itself: a disabled button inside swallows the events React hears.
  useEffect(() => {
    const anchor = anchorRef.current;
    if (!anchor) return undefined;
    const enter = () => setHovered(true);
    const leave = () => {
      setHovered(false);
      setDismissed(false);
    };
    anchor.addEventListener("pointerenter", enter);
    anchor.addEventListener("pointerleave", leave);
    return () => {
      anchor.removeEventListener("pointerenter", enter);
      anchor.removeEventListener("pointerleave", leave);
    };
  }, []);

  useLayoutEffect(() => {
    const anchor = anchorRef.current;
    const tip = tipRef.current;
    if (!shown || !anchor || !tip) return undefined;
    if (canPop && !tip.matches(":popover-open")) tip.showPopover();
    const at = anchor.getBoundingClientRect();
    const above = at.top - GAP - tip.offsetHeight;
    setPlace({
      left: Math.max(EDGE, Math.min(at.left + at.width / 2 - tip.offsetWidth / 2, window.innerWidth - tip.offsetWidth - EDGE)),
      top: above >= EDGE ? above : at.bottom + GAP,
    });
    const hide = () => setDismissed(true);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
      if (canPop && tip.matches(":popover-open")) tip.hidePopover();
    };
  }, [shown, canPop, label]);

  return (
    <span
      ref={anchorRef}
      className={cx(styles.anchor, className)}
      onKeyDown={(event) => {
        if (event.key === "Escape") setDismissed(true);
      }}
      // Shown for the keyboard only: a click's focus is not a wish to read the name again.
      onFocus={(event) => setFocused(event.target.matches(":focus-visible"))}
      onBlur={() => {
        setFocused(false);
        setDismissed(false);
      }}
    >
      {children}
      <span
        ref={tipRef}
        className={cx(styles.tip, shown && styles.shown)}
        popover={canPop ? "manual" : undefined}
        style={place}
        aria-hidden="true"
      >
        {label}
      </span>
    </span>
  );
}

type IconButtonBase = { label: string; icon: IconName; filled?: boolean };
export type IconButtonProps = IconButtonBase &
  ({ href: string; download?: boolean; onClick?: never; disabled?: never } | { href?: never; download?: never; onClick: () => void; disabled?: boolean });

/**
 * A square button (or link) that is only an icon: named by its label, which its tooltip shows.
 */
export function IconButton({ label, icon, filled, ...action }: IconButtonProps) {
  return (
    <Tooltip label={label}>
      {action.href !== undefined ? (
        <a className={styles.iconButton} href={action.href} download={action.download} aria-label={label}>
          <Icon name={icon} filled={filled} />
        </a>
      ) : (
        <button type="button" className={styles.iconButton} onClick={action.onClick} disabled={action.disabled} aria-label={label}>
          <Icon name={icon} filled={filled} />
        </button>
      )}
    </Tooltip>
  );
}
