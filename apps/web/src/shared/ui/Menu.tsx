"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { useTopLayer } from "@/shared/lib/topLayer";
import { useAnchored } from "@/shared/lib/useAnchored";

import styles from "./menu.module.css";

export type MenuItem = { label: string; onSelect: () => void; danger?: boolean };

/**
 * A ⋮ button opening a short list of actions (the WAI-ARIA menu button): arrows move between them,
 * Enter chooses, Escape or a click away closes it and focus returns to the button. In the top
 * layer, beside the button, so nothing clips it.
 */
export function Menu({ label, items }: { label: string; items: readonly MenuItem[] }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const canPop = useTopLayer();
  const place = useAnchored(open, trigger, list, { canPop, maxHeight: 320 });

  useEffect(() => {
    if (!open) return undefined;
    list.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const away = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!list.current?.contains(target) && !trigger.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    const buttons = [...(list.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      buttons[(at + step + buttons.length) % buttons.length]?.focus();
    }
  };

  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={styles.trigger}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((was) => !was)}
      >
        <span aria-hidden="true">⋮</span>
      </button>
      {open ? (
        <ul
          ref={list}
          id={id}
          role="menu"
          aria-label={label}
          className={styles.list}
          popover={canPop ? "manual" : undefined}
          style={place}
          onKeyDown={onKeyDown}
        >
          {items.map((item) => (
            <li key={item.label} role="none">
              <button
                type="button"
                role="menuitem"
                className={item.danger ? `${styles.item} ${styles.danger}` : styles.item}
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}
