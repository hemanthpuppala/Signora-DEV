"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type KeyboardEvent } from "react";

import { cx } from "@/shared/lib/cx";

import fieldStyles from "./field.module.css";
import styles from "./select.module.css";

const LIST_MAX_HEIGHT = 280;
const noSubscription = () => () => {};
const browserHasPopover = () => "showPopover" in HTMLElement.prototype;

export type SelectOption = { value: string; label: string };

export type SelectProps = {
  label: string;
  options: readonly SelectOption[];
  value: string | null;
  onChange: (value: string) => void;
  placeholder?: string;
  /** Submitted with forms through a hidden input. */
  name?: string;
  disabled?: boolean;
  className?: string;
};

/**
 * Select-only combobox (WAI-ARIA APG pattern): focus stays on the trigger, the highlighted option is
 * conveyed with ``aria-activedescendant``. Keys: ArrowDown/ArrowUp open and move, Home/End jump,
 * Enter/Space choose, Escape and Tab close.
 *
 * The open list sits above everything (the browser's top layer, as a manual popover) at the
 * trigger's place, so a dialog or a scrolling panel never clips it; it opens upward when there is
 * no room below, and follows the trigger while anything scrolls.
 */
export function Select({
  label,
  options,
  value,
  onChange,
  placeholder = "Choose…",
  name,
  disabled = false,
  className,
}: SelectProps) {
  const id = useId();
  const listId = `${id}-list`;
  const labelId = `${id}-label`;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<CSSProperties>({});
  // Known only in the browser (not on the server, nor in every test DOM): until then a plain list.
  const canPop = useSyncExternalStore(noSubscription, browserHasPopover, () => false);
  const selectedIndex = options.findIndex((option) => option.value === value);
  const [active, setActive] = useState(Math.max(selectedIndex, 0));

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!open || !list) return undefined;
    if (canPop && !list.matches(":popover-open")) list.showPopover();
    const follow = () => {
      const trigger = triggerRef.current;
      if (!trigger) return;
      const at = trigger.getBoundingClientRect();
      const gap = 6;
      const edge = 16;
      const below = window.innerHeight - at.bottom - gap - edge;
      const above = at.top - gap - edge;
      const wanted = Math.min(list.scrollHeight, LIST_MAX_HEIGHT);
      const up = below < wanted && above > below;
      const width = Math.max(at.width, list.offsetWidth);
      setPlace({
        left: Math.max(edge, Math.min(at.left, window.innerWidth - width - edge)),
        minWidth: at.width,
        maxHeight: Math.max(120, Math.min(LIST_MAX_HEIGHT, up ? above : below)),
        ...(up ? { bottom: window.innerHeight - at.top + gap } : { top: at.bottom + gap }),
      });
    };
    follow();
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    return () => {
      window.removeEventListener("scroll", follow, true);
      window.removeEventListener("resize", follow);
      if (canPop && list.matches(":popover-open")) list.hidePopover();
    };
  }, [open, canPop]);

  function openAt(index: number) {
    setActive(Math.min(Math.max(index, 0), options.length - 1));
    setOpen(true);
  }

  function choose(index: number) {
    const option = options[index];
    if (option) onChange(option.value);
    setOpen(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled || options.length === 0) return;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (open) setActive((i) => Math.min(i + 1, options.length - 1));
        else openAt(selectedIndex >= 0 ? selectedIndex : 0);
        break;
      case "ArrowUp":
        event.preventDefault();
        if (open) setActive((i) => Math.max(i - 1, 0));
        else openAt(selectedIndex >= 0 ? selectedIndex : 0);
        break;
      case "Home":
        if (open) {
          event.preventDefault();
          setActive(0);
        }
        break;
      case "End":
        if (open) {
          event.preventDefault();
          setActive(options.length - 1);
        }
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        if (open) choose(active);
        else openAt(selectedIndex >= 0 ? selectedIndex : 0);
        break;
      case "Escape":
        if (open) {
          event.preventDefault();
          setOpen(false);
        }
        break;
      case "Tab":
        setOpen(false);
        break;
      default:
        break;
    }
  }

  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined;
  const activeId = open ? `${id}-option-${active}` : undefined;

  return (
    <div ref={rootRef} className={cx(fieldStyles.field, styles.select, className)}>
      <span id={labelId} className={fieldStyles.label}>
        {label}
      </span>
      <button
        type="button"
        ref={triggerRef}
        role="combobox"
        className={styles.trigger}
        aria-labelledby={labelId}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={activeId}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openAt(selectedIndex >= 0 ? selectedIndex : 0))}
        onKeyDown={onKeyDown}
      >
        <span className={cx(styles.value, !selected && styles.placeholder)}>
          {selected ? selected.label : placeholder}
        </span>
        <svg className={styles.chevron} width="10" height="10" viewBox="0 0 24 24" aria-hidden="true">
          <path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      </button>
      <ul
        ref={listRef}
        id={listId}
        role="listbox"
        aria-labelledby={labelId}
        className={styles.list}
        popover={canPop ? "manual" : undefined}
        style={place}
        hidden={!open}
      >
        {options.map((option, index) => (
          <li
            key={option.value}
            id={`${id}-option-${index}`}
            role="option"
            aria-selected={option.value === value}
            className={cx(styles.option, index === active && styles.active)}
            onPointerDown={(event) => event.preventDefault()}
            onClick={() => choose(index)}
          >
            {option.label}
          </li>
        ))}
      </ul>
      {name ? <input type="hidden" name={name} value={value ?? ""} /> : null}
    </div>
  );
}
