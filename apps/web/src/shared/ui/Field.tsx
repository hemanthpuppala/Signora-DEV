import { useId, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./field.module.css";
import { Icon } from "./Icon";

type FieldChrome = {
  label: string;
  hint?: string;
  /** Shown under the field and announced; marks the control invalid. */
  error?: string | undefined;
  className?: string;
};

function describedBy(hintId: string, errorId: string, hint?: string, error?: string) {
  const ids = [hint ? hintId : null, error ? errorId : null].filter(Boolean);
  return ids.length ? ids.join(" ") : undefined;
}

export type TextFieldProps = FieldChrome & Omit<InputHTMLAttributes<HTMLInputElement>, "className">;

export function TextField({ label, hint, error, className, id, ...input }: TextFieldProps) {
  const generated = useId();
  const controlId = id ?? generated;
  const hintId = `${controlId}-hint`;
  const errorId = `${controlId}-error`;
  return (
    <div className={cx(styles.field, className)}>
      <label className={styles.label} htmlFor={controlId}>
        {label}
      </label>
      <input
        id={controlId}
        className={styles.control}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(hintId, errorId, hint, error)}
        {...input}
      />
      {hint ? (
        <span id={hintId} className={styles.hint}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span id={errorId} className={styles.error} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}

export type TextAreaProps = FieldChrome &
  Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "className">;

export function TextArea({ label, hint, error, className, id, ...textarea }: TextAreaProps) {
  const generated = useId();
  const controlId = id ?? generated;
  const hintId = `${controlId}-hint`;
  const errorId = `${controlId}-error`;
  return (
    <div className={cx(styles.field, className)}>
      <label className={styles.label} htmlFor={controlId}>
        {label}
      </label>
      <textarea
        id={controlId}
        className={styles.control}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(hintId, errorId, hint, error)}
        {...textarea}
      />
      {hint ? (
        <span id={hintId} className={styles.hint}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span id={errorId} className={styles.error} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}

export type SearchFieldProps = { label: string; className?: string } & Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "className" | "type" | "placeholder"
>;

/**
 * A search box: the underlined field with a magnifier inside on the left, its label as the
 * placeholder (and still the accessible name), so it takes one line.
 */
export function SearchField({ label, className, id, ...input }: SearchFieldProps) {
  const generated = useId();
  const controlId = id ?? generated;
  return (
    <div className={cx(styles.search, className)}>
      <label className={styles.hiddenLabel} htmlFor={controlId}>
        {label}
      </label>
      <Icon name="search" className={styles.searchIcon} />
      <input
        id={controlId}
        type="search"
        className={cx(styles.control, styles.searchControl)}
        placeholder={label}
        autoComplete="off"
        {...input}
      />
    </div>
  );
}
