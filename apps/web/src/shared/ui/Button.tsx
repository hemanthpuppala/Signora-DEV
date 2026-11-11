import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./button.module.css";
import { Icon, type IconName } from "./Icon";

export type ButtonVariant = "primary" | "quiet" | "destructive";

export type ButtonProps = {
  variant?: ButtonVariant;
  /** Adds the trailing arrow used on primary actions ("Create account →"). */
  arrow?: boolean;
  /** Shows ``loadingLabel`` and disables the button while an action is in flight. */
  loading?: boolean;
  loadingLabel?: string;
  compact?: boolean;
  /** A leading icon that says what the action does at a glance (it never replaces the words). */
  icon?: IconName;
  children: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>;

export function Button({
  variant = "primary",
  arrow = false,
  loading = false,
  loadingLabel = "Sending…",
  compact = false,
  icon,
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
      {icon && !loading ? <Icon name={icon} size={15} className={styles.icon} /> : null}
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
 * A page's own action in its head: an icon and its words, small and quiet; on a phone the icon
 * alone, the words still naming it for assistive technology. A link with ``href``.
 */
export function HeadAction({
  icon,
  label,
  variant = "quiet",
  href,
  onClick,
  disabled = false,
}: {
  icon: IconName;
  label: string;
  variant?: ButtonVariant;
  href?: string;
  onClick?: () => void;
  disabled?: boolean;
}) {
  const className = cx(
    styles.button,
    styles.compact,
    styles.headAction,
    variant === "quiet" && styles.quiet,
    variant === "destructive" && styles.destructive,
  );
  const content = (
    <>
      <Icon name={icon} />
      <span className={styles.headActionLabel}>{label}</span>
    </>
  );
  return href ? (
    <Link href={href} className={className}>
      {content}
    </Link>
  ) : (
    <button type="button" className={className} onClick={onClick} disabled={disabled}>
      {content}
    </button>
  );
}
