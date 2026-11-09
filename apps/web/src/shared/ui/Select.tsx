"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type KeyboardEvent } from "react";

import { cx } from "@/shared/lib/cx";

import fieldStyles from "./field.module.css";
import styles from "./select.module.css";

const LIST_MAX_HEIGHT = 280;
const noSubscription = () => () => {};
const browserHasPopover = () => "showPopover" in HTMLElement.prototype;

/** An option; ``hint`` is a quieter word beside it (the group a type belongs to). */
export type SelectOption = { value: string; label: string; hint?: string };

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
  /** A search box at the top of the open list: typing keeps the options whose label or hint has it. */
  searchable?: boolean;
};

/**
 * Select-only combobox (WAI-ARIA APG pattern): focus stays on the trigger, the highlighted option is
 * conveyed with ``aria-activedescendant``. Keys: ArrowDown/ArrowUp open and move, Home/End jump,
 * Enter/Space choose, Escape and Tab close. ``searchable``: the open list starts with a search box
 * that takes the focus and the same keys; its options are announced through it.
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
  searchable = false,
}: SelectProps) {
  const id = useId();
  const listId = `${id}-list`;
  const labelId = `${id}-label`;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<CSSProperties>({});
  // Known only in the browser (not on the server, nor in every test DOM): until then a plain list.
  const canPop = useSyncExternalStore(noSubscription, browserHasPopover, () => false);
  const selectedIndex = options.findIndex((option) => option.value === value);
  // What the list shows: every option, or those matching the search (by label or hint).
  const needle = query.trim().toLowerCase();
  const shown = options
    .map((option, index) => ({ option, index }))
    .filter(({ option }) => !needle || `${option.label} ${option.hint ?? ""}`.toLowerCase().includes(needle));
  const [active, setActive] = useState(Math.max(selectedIndex, 0)); // a position in ``shown``

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

  useEffect(() => {
    if (open && searchable) searchRef.current?.focus();
  }, [open, searchable]);

  function openAt(index: number) {
    setQuery("");
    setActive(Math.min(Math.max(index, 0), options.length - 1));
    setOpen(true);
  }

  function close(refocus: boolean) {
    setOpen(false);
    setQuery("");
    if (refocus && searchable) triggerRef.current?.focus();
  }

  function choose(position: number) {
    const option = shown[position]?.option;
    if (option) onChange(option.value);
    close(true);
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (disabled || options.length === 0) return;
    const last = Math.max(shown.length - 1, 0);
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (open) setActive((i) => Math.min(i + 1, last));
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
          setActive(last);
        }
        break;
      case " ":
        if (open && event.target === searchRef.current) break; // a space typed into the search
        event.preventDefault();
        if (open) choose(active);
        else openAt(selectedIndex >= 0 ? selectedIndex : 0);
        break;
      case "Enter":
        event.preventDefault();
        if (open) choose(active);
        else openAt(selectedIndex >= 0 ? selectedIndex : 0);
        break;
      case "Escape":
        if (open) {
          event.preventDefault();
          close(true);
        }
        break;
      case "Tab":
        close(false);
        break;
      default:
        break;
    }
  }

  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined;
  const activeEntry = shown[active];
  const activeId = open && activeEntry ? `${id}-option-${activeEntry.index}` : undefined;

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
        aria-activedescendant={searchable ? undefined : activeId}
        disabled={disabled}
        onClick={() => (open ? close(false) : openAt(selectedIndex >= 0 ? selectedIndex : 0))}
        onKeyDown={onKeyDown}
      >
        <span className={cx(styles.value, !selected && styles.placeholder)}>
          {selected ? selected.label : placeholder}
        </span>
        <svg className={styles.chevron} width="10" height="10" viewBox="0 0 24 24" aria-hidden="true">
          <path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      </button>
      <div ref={listRef} className={styles.list} popover={canPop ? "manual" : undefined} style={place} hidden={!open}>
        {searchable ? (
          <input
            ref={searchRef}
            type="search"
            role="combobox"
            className={styles.search}
            placeholder="Type to search"
            aria-label={`Search ${label}`}
            aria-expanded={open}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={activeId}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
          />
        ) : null}
        <ul id={listId} role="listbox" aria-labelledby={labelId} className={styles.options}>
          {shown.map(({ option, index }, position) => (
            <li
              key={option.value}
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={option.value === value}
              className={cx(styles.option, position === active && styles.active)}
              onPointerDown={(event) => event.preventDefault()}
              onClick={() => choose(position)}
            >
              <span className={styles.optionLabel}>{option.label}</span>
              {option.hint ? <span className={styles.hint}>{option.hint}</span> : null}
            </li>
          ))}
          {shown.length === 0 ? <li className={styles.empty}>No match</li> : null}
        </ul>
      </div>
      {name ? <input type="hidden" name={name} value={value ?? ""} /> : null}
    </div>
  );
}
