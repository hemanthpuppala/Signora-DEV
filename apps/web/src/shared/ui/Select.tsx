"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { cx } from "@/shared/lib/cx";

import fieldStyles from "./field.module.css";
import styles from "./select.module.css";

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
  const [open, setOpen] = useState(false);
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
      <ul id={listId} role="listbox" aria-labelledby={labelId} className={styles.list} hidden={!open}>
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
