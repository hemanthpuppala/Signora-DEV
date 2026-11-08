import Link from "next/link";
import { useId, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./button.module.css";

export type ButtonVariant = "primary" | "quiet" | "destructive";

export type ButtonProps = {
  variant?: ButtonVariant;
  /** Adds the trailing arrow used on primary actions ("Create account →"). */
  arrow?: boolean;
  /** Shows ``loadingLabel`` and disables the button while an action is in flight. */
  loading?: boolean;
  loadingLabel?: string;
  compact?: boolean;
  children: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>;

export function Button({
  variant = "primary",
  arrow = false,
  loading = false,
  loadingLabel = "Sending…",
  compact = false,
  disabled,
  className,
  type = "button",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(
        styles.button,
        variant === "quiet" && styles.quiet,
        variant === "destructive" && styles.destructive,
        compact && styles.compact,
        className,
      )}
      disabled={disabled === true || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? loadingLabel : children}
      {arrow && !loading ? <span aria-hidden="true">→</span> : null}
    </button>
  );
}

export type TextButtonProps = { children: ReactNode } & ButtonHTMLAttributes<HTMLButtonElement>;

/** Secondary action rendered as tracked uppercase text (prototype .link). */
export function TextButton({ className, type = "button", children, ...rest }: TextButtonProps) {
  return (
    <button type={type} className={cx(styles.textButton, className)} {...rest}>
      {children}
    </button>
  );
}

/** A link that looks like a button (navigation, e.g. "New department →"). */
export function LinkButton({
  href,
  variant = "primary",
  arrow = false,
  children,
}: {
  href: string;
  variant?: ButtonVariant;
  arrow?: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={cx(
        styles.button,
        variant === "quiet" && styles.quiet,
        variant === "destructive" && styles.destructive,
      )}
    >
      {children}
      {arrow ? <span aria-hidden="true">→</span> : null}
    </Link>
  );
}

/**
 * An action this person cannot take, shown disabled with the reason beside it (design-system
 * principle 5: explain a key action a role cannot take instead of failing after a click).
 */
export function UnavailableAction({ children, reason }: { children: ReactNode; reason: string }) {
  const reasonId = useId();
  return (
    <span className={styles.unavailable}>
      <button type="button" className={styles.button} disabled aria-describedby={reasonId}>
        {children}
      </button>
      <span id={reasonId} className={styles.reason}>
        {reason}
      </span>
    </span>
  );
}
