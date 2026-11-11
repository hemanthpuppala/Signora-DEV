import { useId } from "react";

import styles from "./codeField.module.css";
import fieldStyles from "./field.module.css";

export type CodeFieldProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Called once the last digit is in. */
  onComplete?: (value: string) => void;
  length?: number;
  error?: string | undefined;
  disabled?: boolean;
  autoFocus?: boolean;
};

/**
 * A one-time code (Phase 8 §2.1.6): one real input, so a pasted code and the code a phone offers
 * from the email (`autocomplete="one-time-code"`) both work, drawn as a row of boxes. Only digits
 * are kept.
 */
export function CodeField({
  label,
  value,
  onChange,
  onComplete,
  length = 6,
  error,
  disabled,
  autoFocus,
}: CodeFieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const change = (raw: string) => {
    const digits = raw.replace(/\D/g, "").slice(0, length);
    onChange(digits);
    if (digits.length === length) onComplete?.(digits);
  };
  return (
    <div className={fieldStyles.field}>
      <label className={fieldStyles.label} htmlFor={id}>
        {label}
      </label>
      <div
        className={styles.cells}
        style={{ ["--cells" as string]: length }}
        aria-invalid={error ? true : undefined}
      >
        {Array.from({ length }, (_, index) => (
          <span
            key={index}
            className={styles.cell}
            data-active={index === Math.min(value.length, length - 1) ? "true" : undefined}
            aria-hidden="true"
          >
            {value[index] ?? ""}
          </span>
        ))}
        <input
          id={id}
          className={styles.input}
          value={value}
          onChange={(event) => change(event.target.value)}
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          maxLength={length}
          disabled={disabled}
          // The code screen has one job; its field takes focus as the screen opens.
          autoFocus={autoFocus}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
        />
        <span className={styles.focusRing} aria-hidden="true" />
      </div>
      {error ? (
        <span id={errorId} className={fieldStyles.error} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}
