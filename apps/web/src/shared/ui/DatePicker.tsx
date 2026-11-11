"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { useTopLayer } from "@/shared/lib/topLayer";
import { useAnchored } from "@/shared/lib/useAnchored";

import styles from "./datePicker.module.css";
import fieldStyles from "./field.module.css";
import { Icon } from "./Icon";
import { Select } from "./Select";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const FIRST_YEAR = 1900;
const LAST_YEAR = 2100;

type Day = { year: number; month: number; day: number }; // month 0-11

const pad = (n: number) => String(n).padStart(2, "0");
export const isoOf = (d: Day) => `${d.year}-${pad(d.month + 1)}-${pad(d.day)}`;

function parse(iso: string): Day | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]) - 1, day: Number(match[3]) };
}

const daysIn = (year: number, month: number) => new Date(Date.UTC(year, month + 1, 0)).getUTCDate();

function moved(d: Day, days: number): Day {
  const at = new Date(Date.UTC(d.year, d.month, d.day + days));
  return { year: at.getUTCFullYear(), month: at.getUTCMonth(), day: at.getUTCDate() };
}

function monthMoved(d: Day, months: number): Day {
  const index = d.year * 12 + d.month + months;
  const year = Math.floor(index / 12);
  const month = index - year * 12;
  return { year, month, day: Math.min(d.day, daysIn(year, month)) };
}

function today(): Day {
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth(), day: now.getDate() };
}

/** "Nov 11, 2026": how a picked date reads in its field. */
export function dateInWords(iso: string): string {
  const d = parse(iso);
  return d ? `${MONTHS[d.month]?.slice(0, 3)} ${d.day}, ${d.year}` : "";
}

/**
 * A month of days to choose from: arrows move a day or a week, Page Up and Page Down a month,
 * Enter or Space chooses. One day in the grid takes focus at a time (a roving tab stop).
 */
export function Calendar({ value, onChange, label }: { value: string; onChange: (iso: string) => void; label: string }) {
  const chosen = parse(value);
  const [focus, setFocus] = useState<Day>(chosen ?? today());
  const grid = useRef<HTMLDivElement>(null);
  const focusDay = useRef(false);
  const now = today();

  useEffect(() => {
    if (!focusDay.current) return;
    focusDay.current = false;
    grid.current?.querySelector<HTMLButtonElement>(`[data-iso="${isoOf(focus)}"]`)?.focus();
  }, [focus]);

  const go = (next: Day) => {
    if (next.year < FIRST_YEAR || next.year > LAST_YEAR) return;
    focusDay.current = true;
    setFocus(next);
  };

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, () => Day> = {
      ArrowLeft: () => moved(focus, -1),
      ArrowRight: () => moved(focus, 1),
      ArrowUp: () => moved(focus, -7),
      ArrowDown: () => moved(focus, 7),
      PageUp: () => monthMoved(focus, -1),
      PageDown: () => monthMoved(focus, 1),
    };
    const move = moves[event.key];
    if (move) {
      event.preventDefault();
      go(move());
    }
  }

  const lead = new Date(Date.UTC(focus.year, focus.month, 1)).getUTCDay();
  const count = daysIn(focus.year, focus.month);
  const years = Array.from({ length: LAST_YEAR - FIRST_YEAR + 1 }, (_, i) => String(LAST_YEAR - i));
  return (
    <div className={styles.calendar}>
      <div className={styles.head}>
        <button type="button" className={styles.step} aria-label="Previous month" onClick={() => setFocus(monthMoved(focus, -1))}>
          <Icon name="left" />
        </button>
        <span className={styles.month} aria-live="polite">
          {MONTHS[focus.month]}
        </span>
        <Select
          label="Year"
          options={years.map((year) => ({ value: year, label: year }))}
          value={String(focus.year)}
          onChange={(year) => setFocus({ ...focus, year: Number(year), day: Math.min(focus.day, daysIn(Number(year), focus.month)) })}
        />
        <button type="button" className={styles.step} aria-label="Next month" onClick={() => setFocus(monthMoved(focus, 1))}>
          <Icon name="right" />
        </button>
      </div>
      <div ref={grid} className={styles.grid} role="grid" aria-label={`${label}: ${MONTHS[focus.month]} ${focus.year}`} onKeyDown={onKeyDown}>
        {WEEKDAYS.map((day) => (
          <span key={day} className={styles.weekday} role="columnheader" aria-hidden="true">
            {day}
          </span>
        ))}
        {Array.from({ length: lead }, (_, i) => (
          <span key={`lead-${i}`} className={styles.outside} aria-hidden="true" />
        ))}
        {Array.from({ length: count }, (_, i) => {
          const day = { year: focus.year, month: focus.month, day: i + 1 };
          const iso = isoOf(day);
          return (
            <button
              key={iso}
              type="button"
              className={styles.day}
              data-iso={iso}
              role="gridcell"
              aria-selected={iso === value}
              aria-label={`${MONTHS[day.month]} ${day.day}, ${day.year}`}
              data-today={iso === isoOf(now) || undefined}
              tabIndex={day.day === focus.day ? 0 : -1}
              onClick={() => onChange(iso)}
            >
              {day.day}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export type DatePickerProps = {
  label: string;
  value: string; // "YYYY-MM-DD" once a whole date is in; otherwise what was typed
  onChange: (value: string) => void;
  error?: string | undefined;
  hint?: string;
  /** The calendar shown in place (inside a phone's bottom sheet), not opened from a button. */
  inline?: boolean;
};

/** A typed date as YYYY-MM-DD: "12/1/2026" (month first) or "2026-12-01"; null until whole. */
export function typedDate(text: string): string | null {
  const us = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(text.trim());
  const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(text.trim());
  const [year, month, day] = us
    ? [Number(us[3]), Number(us[1]), Number(us[2])]
    : iso
      ? [Number(iso[1]), Number(iso[2]), Number(iso[3])]
      : [0, 0, 0];
  if (!year || month < 1 || month > 12 || day < 1 || day > daysIn(year, month - 1)) return null;
  return isoOf({ year, month: month - 1, day });
}

/** "12/01/2026": how a date reads in its box. */
function shown(value: string): string {
  const d = parse(value);
  return d ? `${pad(d.month + 1)}/${pad(d.day)}/${d.year}` : value;
}

/**
 * The design system's date field (Phase 8 §5.6): type it ("12/01/2026", or "2026-12-01"), or
 * choose it from the calendar its button opens. The value is YYYY-MM-DD once a whole date is in;
 * anything else is passed on as typed, for the form to say what is wrong.
 */
export function DatePicker({ label, value, onChange, error, hint, inline = false }: DatePickerProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(() => shown(value));
  const trigger = useRef<HTMLButtonElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const canPop = useTopLayer();
  const place = useAnchored(open, trigger, popover, { canPop, maxHeight: 420 });

  // A value set from outside (a calendar choice, a reset) shows in the box.
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    if (typedDate(text) !== value) setText(shown(value));
  }

  useEffect(() => {
    if (!open) return undefined;
    const away = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!popover.current?.contains(target) && !trigger.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  useEffect(() => {
    if (open) popover.current?.querySelector<HTMLButtonElement>('[tabindex="0"]')?.focus();
  }, [open]);

  if (inline) {
    return (
      <div className={fieldStyles.field}>
        <span className={fieldStyles.label}>{label}</span>
        <Calendar label={label} value={value} onChange={onChange} />
        {error ? <span className={fieldStyles.error} role="alert">{error}</span> : null}
      </div>
    );
  }
  return (
    <div className={fieldStyles.field}>
      <label className={fieldStyles.label} htmlFor={id}>
        {label}
      </label>
      <div className={styles.box}>
        <input
          id={id}
          className={fieldStyles.control}
          inputMode="numeric"
          autoComplete="off"
          placeholder="MM/DD/YYYY"
          maxLength={10}
          value={text}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          onChange={(event) => {
            const typed = event.target.value.replace(/[^0-9/-]/g, "");
            setText(typed);
            onChange(typedDate(typed) ?? typed);
          }}
        />
        <button
          ref={trigger}
          type="button"
          className={styles.open}
          aria-label={`Choose ${label} from a calendar`}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen((was) => !was)}
        >
          <Icon name="calendar" />
        </button>
      </div>
      {open ? (
        <div
          ref={popover}
          className={styles.popover}
          role="dialog"
          aria-label={label}
          popover={canPop ? "manual" : undefined}
          style={place}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              setOpen(false);
              trigger.current?.focus();
            }
          }}
        >
          <Calendar
            label={label}
            value={value}
            onChange={(iso) => {
              setText(shown(iso));
              onChange(iso);
              setOpen(false);
              trigger.current?.focus();
            }}
          />
        </div>
      ) : null}
      {hint ? <span className={fieldStyles.hint}>{hint}</span> : null}
      {error ? (
        <span id={`${id}-error`} className={fieldStyles.error} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}
