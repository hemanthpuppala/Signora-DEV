import type { ReactNode } from "react";

import styles from "./layout.module.css";
import { Eyebrow } from "./Typography";

/** A titled block of a console page (prototype .section). */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section} aria-label={title}>
      <Eyebrow>{title}</Eyebrow>
      {children}
    </section>
  );
}

/** Fields side by side that wrap on narrow screens, aligned at their bottom (prototype .fields). */
export function FieldGrid({ children }: { children: ReactNode }) {
  return <div className={styles.fields}>{children}</div>;
}
