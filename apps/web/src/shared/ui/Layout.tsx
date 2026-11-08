import type { ReactNode } from "react";

import styles from "./layout.module.css";
import { Eyebrow } from "./Typography";

/** A page's title block with its actions at the end (prototype .headrow / .actions). */
export function HeadRow({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className={styles.headRow}>
      <div className={styles.headTitle}>{children}</div>
      {actions ? <div className={styles.headActions}>{actions}</div> : null}
    </div>
  );
}

/** A titled block of a console page (prototype .section). */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section} aria-label={title}>
      <Eyebrow>{title}</Eyebrow>
      {children}
    </section>
  );
}

/** Fields side by side that wrap on narrow screens, lined up by their labels (prototype .fields). */
export function FieldGrid({ children }: { children: ReactNode }) {
  return <div className={styles.fields}>{children}</div>;
}

/** A button placed in a ``FieldGrid``: it sits on the same line as the inputs beside it. */
export function FieldAction({ children }: { children: ReactNode }) {
  return (
    <div className={styles.action}>
      <span className={styles.actionLabel} aria-hidden="true" />
      <div className={styles.actionSlot}>{children}</div>
    </div>
  );
}
