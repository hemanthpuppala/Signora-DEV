"use client";

import { Checkbox, Select, SmallText, TextArea, TextField } from "@/shared/ui";

import type { FormField } from "./api";
import styles from "./envelopes.module.css";

/** The browser's input type for a field type, so phones show the right keyboard. */
function inputType(holds: FormField["holds"]): string {
  switch (holds) {
    case "email":
      return "email";
    case "phone":
      return "tel";
    case "url":
      return "url";
    case "date":
    case "date_of_birth":
      return "date";
    default:
      return "text";
  }
}

const NUMERIC = new Set<FormField["holds"]>(["number", "currency", "percent"]);
const WHOLE = new Set<FormField["holds"]>(["day", "year"]);
const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;

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
}: {
  field: FormField;
  /** Say "Required" under this field: when its group's note does not already say so. */
  markRequired?: boolean;
  value: string;
  onChange: (value: string) => void;
  error?: string | undefined;
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
  if (field.holds === "note") {
    return <TextArea label={label} {...hint} maxLength={2000} value={value} error={error} onChange={(event) => onChange(event.target.value)} />;
  }
  return (
    <TextField
      label={label}
      {...hint}
      type={inputType(field.holds)}
      inputMode={NUMERIC.has(field.holds) ? "decimal" : WHOLE.has(field.holds) ? "numeric" : undefined}
      {...(field.holds === "day"
        ? { placeholder: "1 to 31", maxLength: 2 }
        : field.holds === "year"
          ? { placeholder: "2026", maxLength: 4 } // the whole year; the field writes 26 where the form prints 20
          : { maxLength: 2000 })}
      value={value}
      error={error}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}
