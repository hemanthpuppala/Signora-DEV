import type { InputHTMLAttributes, ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./choice.module.css";

type ChoiceProps = {
  children: ReactNode;
  className?: string;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "className" | "children">;

/** Native checkbox styled as the prototype's square box; keeps native keyboard and form behaviour. */
export function Checkbox({ children, className, ...input }: ChoiceProps) {
  return (
    <label className={cx(styles.choice, className)}>
      <input type="checkbox" className={cx(styles.input, styles.checkbox)} {...input} />
      <span>{children}</span>
    </label>
  );
}

/** Native radio styled as the prototype's round dot. Group radios with the same ``name``. */
export function Radio({ children, className, ...input }: ChoiceProps) {
  return (
    <label className={cx(styles.choice, className)}>
      <input type="radio" className={cx(styles.input, styles.radio)} {...input} />
      <span>{children}</span>
    </label>
  );
}
