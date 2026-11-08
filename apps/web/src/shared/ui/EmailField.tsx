"use client";

import { useState, type ChangeEvent, type FocusEvent } from "react";

import { INVALID_EMAIL, looksLikeEmail } from "@/shared/lib/email";

import { TextField, type TextFieldProps } from "./Field";

export type EmailFieldProps = Omit<TextFieldProps, "type">;

/**
 * Email input used everywhere an address is typed. A malformed address is pointed out when the field
 * loses focus (never while typing) with the server's own wording; ``error`` from the server wins.
 */
export function EmailField({ error, onBlur, onChange, ...props }: EmailFieldProps) {
  const [malformed, setMalformed] = useState(false);
  const blur = (event: FocusEvent<HTMLInputElement>) => {
    const value = event.target.value;
    setMalformed(value.trim() !== "" && !looksLikeEmail(value));
    onBlur?.(event);
  };
  const change = (event: ChangeEvent<HTMLInputElement>) => {
    if (malformed && looksLikeEmail(event.target.value)) setMalformed(false);
    onChange?.(event);
  };
  const shown = error ?? (malformed ? INVALID_EMAIL : undefined);
  return (
    <TextField
      {...props}
      {...(shown ? { error: shown } : {})}
      type="email"
      inputMode="email"
      autoCapitalize="none"
      spellCheck={false}
      onBlur={blur}
      onChange={change}
    />
  );
}
