"use client";

import { useState, type FocusEvent, type ChangeEvent } from "react";

import { TextButton } from "./Button";
import { TextField, type TextFieldProps } from "./Field";
import styles from "./field.module.css";

export type PasswordFieldProps = Omit<TextFieldProps, "type"> & {
  /** "new-password" when choosing one, "current-password" when signing in, "off" for one the
   * person must type themselves (the current password, to change it). */
  autoComplete: "new-password" | "current-password" | "off";
};

/** Length as the server counts it: after Unicode NFKC normalisation. */
const counted = (value: string) => value.normalize("NFKC").length;

/**
 * Password input with a show/hide toggle; paste allowed; labelled for password managers.
 *
 * When choosing a password (``new-password`` with ``minLength``), a too-short entry is pointed out
 * when the field loses focus (not while typing): the hint turns into the error. Other rules, like
 * "too common", come back from the server as ``error``.
 */
export function PasswordField({
  autoComplete,
  minLength,
  hint,
  error,
  onBlur,
  onChange,
  ...props
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  const [tooShort, setTooShort] = useState(false);
  const checksLength = autoComplete === "new-password" && typeof minLength === "number";

  const blur = (event: FocusEvent<HTMLInputElement>) => {
    if (checksLength) {
      const value = event.target.value;
      setTooShort(value !== "" && counted(value) < minLength);
    }
    onBlur?.(event);
  };
  const change = (event: ChangeEvent<HTMLInputElement>) => {
    if (tooShort && checksLength && counted(event.target.value) >= minLength) setTooShort(false);
    onChange?.(event);
  };

  // The hint is the server's rule; it doubles as the too-short message.
  const shownError = error ?? (tooShort ? (hint ?? "Too short") : undefined);
  return (
    <div className={styles.passwordWrap}>
      <TextField
        {...props}
        {...(minLength !== undefined ? { minLength } : {})}
        {...(shownError ? { error: shownError } : hint ? { hint } : {})}
        type={visible ? "text" : "password"}
        autoComplete={autoComplete}
        autoCapitalize="none"
        spellCheck={false}
        onBlur={blur}
        onChange={change}
      />
      <TextButton
        className={styles.reveal}
        aria-pressed={visible}
        aria-label={visible ? "Hide password" : "Show password"}
        onClick={() => setVisible((shown) => !shown)}
      >
        {visible ? "Hide" : "Show"}
      </TextButton>
    </div>
  );
}
