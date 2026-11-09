import type { ReactNode } from "react";

import styles from "./facts.module.css";

export type Fact = { term: string; value: ReactNode };

/**
 * Facts about one thing as label and value (an envelope's settings, a certificate's hashes): a
 * hairline panel, one row each, the label quiet on the left and the value on the right; the label
 * over its value on a phone. A definition list, so each value is read with its label.
 */
export function FactList({ label, facts }: { label: string; facts: readonly Fact[] }) {
  return (
    <dl className={styles.facts} aria-label={label}>
      {facts.map((fact) => (
        <div key={fact.term} className={styles.fact}>
          <dt className={styles.term}>{fact.term}</dt>
          <dd className={styles.value}>{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}
