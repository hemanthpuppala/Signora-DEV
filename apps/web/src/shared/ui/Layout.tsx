import Link from "next/link";
import type { FormHTMLAttributes, ReactNode } from "react";

import { InfoTip } from "./InfoTip";
import styles from "./layout.module.css";
import { Eyebrow } from "./Typography";

export type Back = { href: string; label: string };

/**
 * The way back to the page above, in the eyebrow's place: "‹ Documents". Named "Back to …" for
 * assistive technology (the visible words are part of the name).
 */
export function BackLink({ href, label }: Back) {
  return (
    <Link href={href} className={styles.back} aria-label={`Back to ${label}`}>
      <span aria-hidden="true">‹</span> {label}
    </Link>
  );
}

/**
 * A page's title block with its actions at the end (prototype .headrow / .actions); ``back`` puts
 * the way to the page above over the title, so no page needs a separate Back button, and
 * ``backActions`` sit at the end of that same line (a page's own buttons, out of the title's way).
 */
export function HeadRow({
  children,
  actions,
  back,
  backActions,
}: {
  children: ReactNode;
  actions?: ReactNode;
  back?: Back;
  backActions?: ReactNode;
}) {
  return (
    <div className={styles.headRow}>
      <div className={styles.headTitle}>
        {back && backActions ? (
          <div className={styles.backLine}>
            <BackLink {...back} />
            <div className={styles.backActions}>{backActions}</div>
          </div>
        ) : back ? (
          <BackLink {...back} />
        ) : null}
        {children}
      </div>
      {actions ? <div className={styles.headActions}>{actions}</div> : null}
    </div>
  );
}

/** A form that is a whole page (head row, sections, submit): spaced like the page itself. */
export function PageForm(form: Omit<FormHTMLAttributes<HTMLFormElement>, "className">) {
  return <form className={styles.pageForm} {...form} />;
}

/** Groups of settings in one hairline panel, one row each (prototype .blocks). */
export function Blocks({ children }: { children: ReactNode }) {
  return <div className={styles.blocks}>{children}</div>;
}

/**
 * One row of ``Blocks`` (prototype .block): its title, and a line saying what it is for, on the
 * left; its fields and lists on the right (under the title on a phone).
 */
export function Block({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className={styles.block} aria-label={title}>
      <div className={styles.blockHead}>
        <p className={styles.blockTitle}>{title}</p>
        {hint ? <p className={styles.blockHint}>{hint}</p> : null}
      </div>
      <div className={styles.blockBody}>{children}</div>
    </section>
  );
}

/** A titled block of a console page (prototype .section); ``info`` adds a "?" that explains it. */
export function Section({ title, info, children }: { title: string; info?: ReactNode; children: ReactNode }) {
  return (
    <section className={styles.section} aria-label={title}>
      {info ? (
        <div className={styles.sectionTitle}>
          <Eyebrow>{title}</Eyebrow>
          <InfoTip label={title}>{info}</InfoTip>
        </div>
      ) : (
        <Eyebrow>{title}</Eyebrow>
      )}
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
