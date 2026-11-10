import Link from "next/link";
import type { FormHTMLAttributes, ReactNode } from "react";

import { Icon } from "./Icon";
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

/**
 * A document beside its details (the document page, review, an envelope): a ``ViewerPane``
 * (notices, then the PDF viewer last, which takes the height left) and a ``DetailsPane``, its
 * sections divided by hairlines. From laptop width the two sit side by side, one screen tall, each
 * scrolling inside itself; on phones they are one column.
 *
 * A screen's ``ActionBar`` is the layout's first child, before the panes. From laptop width it
 * heads the details column, above what scrolls, so the viewer keeps the window's full height; on
 * phones it comes first and stays under the top bar while the whole page scrolls, so Save is
 * never below the document. Use it with ``ConsoleShell width="full"``.
 */
export function ViewerLayout({ children }: { children: ReactNode }) {
  return <div className={styles.viewerLayout}>{children}</div>;
}

/** The document side of a ``ViewerLayout``. */
export function ViewerPane({ children }: { children: ReactNode }) {
  return <div className={styles.viewer}>{children}</div>;
}

/** The details side of a ``ViewerLayout``. */
export function DetailsPane({ children }: { children: ReactNode }) {
  return <div className={styles.details}>{children}</div>;
}

/**
 * A titled block of a console page (prototype .section); ``info`` adds a "?" that explains it,
 * and ``action`` puts the block's own action (an icon button) at the end of its title line, so it
 * takes no line of its own.
 * ``collapsible``: its title line opens and closes it in place (a native ``<details>``, so it
 * works by keyboard and is announced as expanded or collapsed), with ``count`` beside the title
 * and a chevron at the end; open to begin with unless ``defaultOpen`` is false. A screen that must
 * open it itself (to show something chosen elsewhere) keeps its state: ``open`` and
 * ``onOpenChange``.
 */
export function Section({
  title,
  info,
  action,
  count,
  collapsible = false,
  defaultOpen = true,
  open,
  onOpenChange,
  children,
}: {
  title: string;
  info?: ReactNode;
  action?: ReactNode;
  count?: number | undefined;
  collapsible?: boolean;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
}) {
  const heading = (
    <>
      <Eyebrow>{title}</Eyebrow>
      {count !== undefined ? <span className={styles.count}>{count}</span> : null}
      {info ? (
        // Its "?" explains the section without opening or closing it.
        <span className={styles.infoSlot} onClick={(event) => event.preventDefault()}>
          <InfoTip label={title}>{info}</InfoTip>
        </span>
      ) : null}
      {action ? (
        // Pressing it acts; it never opens or closes the section.
        <span className={styles.actionSlotEnd} onClick={(event) => event.preventDefault()}>
          {action}
        </span>
      ) : null}
    </>
  );
  if (!collapsible) {
    return (
      <section className={styles.section} aria-label={title}>
        {info || action || count !== undefined ? <div className={styles.sectionTitle}>{heading}</div> : <Eyebrow>{title}</Eyebrow>}
        {children}
      </section>
    );
  }
  return (
    <section className={styles.section} aria-label={title}>
      <details
        className={styles.collapse}
        open={open ?? defaultOpen}
        onToggle={onOpenChange ? (event) => onOpenChange(event.currentTarget.open) : undefined}
      >
        <summary className={styles.summary}>
          {heading}
          <Icon name="chevron" size={14} className={styles.chevron} />
        </summary>
        <div className={styles.sectionBody}>{children}</div>
      </details>
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
