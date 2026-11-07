"use client";

import { useState } from "react";

import { TextButton } from "./Button";
import { TextField, type TextFieldProps } from "./Field";
import styles from "./field.module.css";

export type PasswordFieldProps = Omit<TextFieldProps, "type"> & {
  /** "new-password" when choosing one, "current-password" when signing in. */
  autoComplete: "new-password" | "current-password";
};

/** Password input with a show/hide toggle; paste allowed; labelled for password managers. */
export function PasswordField({ autoComplete, ...props }: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  return (
    <div className={styles.passwordWrap}>
      <TextField
        {...props}
        type={visible ? "text" : "password"}
        autoComplete={autoComplete}
        autoCapitalize="none"
        spellCheck={false}
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
