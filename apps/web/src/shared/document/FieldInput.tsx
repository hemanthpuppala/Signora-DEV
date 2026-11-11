"use client";

import { Checkbox, DatePicker, Select, SmallText, TextArea, TextField } from "@/shared/ui";

import styles from "./document.module.css";
import type { InputField } from "./types";
import { MONTHS, number } from "./typeset";

/** The browser's input type for a field type, so phones show the right keyboard. */
function inputType(holds: InputField["holds"]): string {
  switch (holds) {
    case "email":
      return "email";
    case "phone":
      return "tel";
    case "url":
      return "url";
    default:
      return "text";
  }
}

const NUMERIC = new Set<InputField["holds"]>(["number", "currency", "percent"]);
const WHOLE = new Set<InputField["holds"]>(["day", "year"]);
/**
 * One field of the document as an input of its type (Phase 7 §2): a date picker for a date; for a
 * date split into boxes, the month by name and the day or year by number; a choice's own options,
 * a checkbox, a note as a paragraph, text otherwise. The value is the text the API takes (a checkbox "true", a choice its option's value); the server judges it (review.formats).
 */
export function FieldInput({
  field,
  value,
  onChange,
  error,
  markRequired = false,
  onBlur,
  inlineDate = false,
}: {
  field: InputField;
  /** Say "Required" under this field: when its group's note does not already say so. */
  markRequired?: boolean;
  value: string;
  onChange: (value: string) => void;
  error?: string | undefined;
  /** The person left the box: what it holds can be judged now, not while they type. */
  onBlur?: () => void;
  /** A whole date as a calendar shown in place (a phone's bottom sheet), not opened from a field. */
  inlineDate?: boolean;
}) {
  const label = field.holds === "other" && field.holds_label ? `${field.label} (${field.holds_label})` : field.label;
  const hint = markRequired && field.required ? { hint: "Required" } : {};
  if (field.holds === "checkbox") {
    return (
      <div>
        <Checkbox checked={value === "true"} onChange={(event) => onChange(event.target.checked ? "true" : "")}>
          {label}
        </Checkbox>
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
      </div>
    );
  }
  if (field.holds === "choice") {
    return (
      <div>
        <Select
          label={label}
          options={[{ value: "", label: "Not chosen" }, ...field.options.map((o) => ({ value: o.value, label: o.text }))]}
          value={value}
          onChange={onChange}
        />
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
      </div>
    );
  }
  if (field.holds === "month") {
    // A part of a date split into boxes: the month picked by name, kept as its number; the field's
    // format writes it as a name or a number.
    return (
      <div>
        <Select
          label={label}
          options={[{ value: "", label: "Not chosen" }, ...MONTHS.map((m, i) => ({ value: String(i + 1), label: m }))]}
          value={value}
          onChange={onChange}
        />
        {hint.hint ? <SmallText>{hint.hint}</SmallText> : null}
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
      </div>
    );
  }
  if (field.holds === "date" || field.holds === "date_of_birth") {
    // A whole date: the design system's calendar (Phase 8 §5.6), kept as YYYY-MM-DD.
    return <DatePicker label={label} {...hint} value={value} onChange={onChange} error={error} inline={inlineDate} />;
  }
  if (field.holds === "note") {
    return <TextArea label={label} {...hint} maxLength={2000} value={value} error={error} onChange={(event) => onChange(event.target.value)} />;
  }
  const year = field.holds === "year" ? (field.format === "YY" ? 2 : 4) : null;
  return (
    <TextField
      label={label}
      {...hint}
      type={inputType(field.holds)}
      inputMode={NUMERIC.has(field.holds) ? "decimal" : WHOLE.has(field.holds) ? "numeric" : undefined}
      autoComplete="off" // the document's values, not the sender's own details
      {...(field.holds === "day"
        ? { placeholder: "1 to 31", maxLength: 2 }
        : year !== null
          ? // As the blank prints it: two digits after a printed "20" (kept as the whole year).
            { placeholder: year === 2 ? "26" : "2026", maxLength: year }
          : { maxLength: 2000 })}
      value={value}
      error={error}
      onBlur={onBlur}
      onChange={(event) => {
        const next = accepted(field.holds, event.target.value);
        if (next !== null) onChange(next);
      }}
    />
  );
}

/** What each type may be typed with; anything else never reaches the box (the server checks again). */
const TYPED: Partial<Record<InputField["holds"], RegExp>> = {
  day: /[^0-9]/g,
  year: /[^0-9]/g,
  number: /[^0-9.,-]/g,
  currency: /[^0-9.,]/g,
  percent: /[^0-9.%]/g,
  phone: /[^0-9+()\-. ]/g,
};

/**
 * The text a keystroke or a paste leaves in the box: characters its type cannot hold are dropped,
 * and a day stays within 1 to 31 (a keystroke that would leave it outside is refused: ``null``).
 */
export function accepted(holds: InputField["holds"], raw: string): string | null {
  const strip = TYPED[holds];
  const text = strip ? raw.replace(strip, "") : raw;
  if (holds === "day" && text !== "" && (Number(text) > 31 || /^0{2}/.test(text))) return null;
  return text;
}

/**
 * Why a day, a year or a number cannot be kept as typed, in the server's own words
 * (review.formats), so it is said at the box and not on Send; nothing when it can be, or for any
 * other type.
 */
export function refused(holds: InputField["holds"], text: string): string | undefined {
  if (text === "") return undefined;
  if (holds === "day" && !(Number(text) >= 1 && Number(text) <= 31)) return "Enter a day from 1 to 31";
  if (holds === "year" && !/^(\d{2}|\d{4})$/.test(text)) return "Enter a year, such as 2026";
  if (NUMERIC.has(holds)) {
    const judged = number(holds, text);
    return "refused" in judged ? judged.refused : undefined;
  }
  return undefined;
}
