import Link from "next/link";
import type { ReactNode } from "react";

import styles from "./documentCard.module.css";
import { IconButton } from "./Tooltip";

/** Cards for documents, side by side from about 340px each (prototype .dgrid). */
export function DocumentGrid({ children, label }: { children: ReactNode; label: string }) {
  return (
    <ul className={styles.grid} aria-label={label}>
      {children}
    </ul>
  );
}

/**
 * One document as a card (prototype .dcard): a page with its type, the name and version, a line
 * of facts, its status at the top right, and a footer with a download and where the card leads.
 * The name is the link, stretched over the whole card; the download is its own link above it
 * (links cannot be nested).
 */
export function DocumentCard({
  href,
  kind,
  title,
  version,
  facts,
  status,
  download,
  action = "Open",
}: {
  href: string;
  /** The tag on the page: "PDF" or "DOC". */
  kind: string;
  title: string;
  /** "V2"; none before a version is ready. */
  version?: string | undefined;
  facts: string;
  /** Shown at the top right (a status dot). */
  status: ReactNode;
  download?: { href: string; label: string } | undefined;
  action?: string;
}) {
  return (
    <li className={styles.item}>
      <article className={styles.card}>
        <span className={styles.thumb} aria-hidden="true">
          <b>{kind}</b>
          <i />
          <i />
          <i />
          <i />
          <i />
        </span>
        <span className={styles.main}>
          <span className={styles.top}>
            <span className={styles.title}>
              <Link href={href} className={styles.name}>
                {title}
              </Link>
              {version ? <span className={styles.version}>{version}</span> : null}
            </span>
            <span className={styles.status}>{status}</span>
          </span>
          <span className={styles.facts}>{facts}</span>
        </span>
        <span className={styles.foot}>
          {download ? (
            <span className={styles.above}>
              <IconButton icon="download" label={download.label} href={download.href} download />
            </span>
          ) : null}
          <span className={styles.go} aria-hidden="true">{`${action} →`}</span>
        </span>
      </article>
    </li>
  );
}
