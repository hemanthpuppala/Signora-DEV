"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

import { cx } from "@/shared/lib/cx";
import { useTopLayer } from "@/shared/lib/topLayer";
import { useAnchored } from "@/shared/lib/useAnchored";

import fieldStyles from "./field.module.css";
import styles from "./select.module.css";

const LIST_MAX_HEIGHT = 280;
/** From this many options a list starts with a search box: shorter ones are read at a glance. */
export const SEARCH_FROM = 8;
/** A finger, not a mouse: a keyboard raised unasked would cover the list it is for. */
const touchFirst = () => window.matchMedia?.("(pointer: coarse)").matches ?? false;

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
  /**
   * A search box at the top of the open list: typing keeps the options whose label or hint has
   * it. By default a list of ``SEARCH_FROM`` options or more has one; set it to force either way.
   */
  searchable?: boolean;
  /** The label is read aloud but not shown: a toolbar's control whose value says what it is
   * ("Newest first"), beside a search box. */
  labelHidden?: boolean;
};

/**
 * Select-only combobox (WAI-ARIA APG pattern): focus stays on the trigger, the highlighted option is
 * conveyed with ``aria-activedescendant``. Keys: ArrowDown/ArrowUp open and move, Home/End jump,
 * Enter/Space choose, Escape and Tab close; the highlighted option is always in view.
 * ``searchable``: the open list starts with a search box that takes the focus and the same keys;
 * its options are announced through it. On a touch screen the focus stays on the trigger until the
 * search box is tapped, so opening a list never raises the keyboard over it.
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
  searchable: searchableProp,
  labelHidden = false,
}: SelectProps) {
  const searchable = searchableProp ?? options.length >= SEARCH_FROM;
  const id = useId();
  const listId = `${id}-list`;
  const labelId = `${id}-label`;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const optionsRef = useRef<HTMLUListElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const canPop = useTopLayer();
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

  const place = useAnchored(open, triggerRef, listRef, { canPop, maxHeight: LIST_MAX_HEIGHT });

  useEffect(() => {
    if (open && searchable && !touchFirst()) searchRef.current?.focus();
  }, [open, searchable]);

  // The highlighted option stays in view: the list is moved only as far as it takes, and nothing
  // around the list moves (scrollIntoView would scroll the page too).
  const activeIndex = shown[active]?.index;
  useLayoutEffect(() => {
    const list = optionsRef.current;
    const option = open && activeIndex !== undefined ? document.getElementById(`${id}-option-${activeIndex}`) : null;
    if (!list || !option) return;
    const top = option.offsetTop - list.offsetTop;
    if (top < list.scrollTop) list.scrollTop = top;
    else if (top + option.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = top + option.offsetHeight - list.clientHeight;
  }, [open, activeIndex, id, place]);

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
      <span id={labelId} className={labelHidden ? fieldStyles.hiddenLabel : fieldStyles.label}>
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
        <ul ref={optionsRef} id={listId} role="listbox" aria-labelledby={labelId} className={styles.options}>
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
