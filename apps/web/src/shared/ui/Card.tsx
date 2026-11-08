import Link from "next/link";
import type { ReactNode } from "react";

import styles from "./card.module.css";

/** Cards side by side that wrap on narrow screens (prototype .pgrid). */
export function CardGrid({ children, label }: { children: ReactNode; label: string }) {
  return (
    <ul className={styles.grid} aria-label={label}>
      {children}
    </ul>
  );
}

export type CardStat = { label: string; value: number };

/** A linked card with a title, a description and a three-figure footer (prototype .pcard). */
export function StatCard({
  href,
  title,
  description,
  stats,
  meta,
}: {
  href: string;
  title: string;
  description?: string;
  stats: readonly CardStat[];
  meta?: ReactNode;
}) {
  return (
    <li className={styles.item}>
      <Link href={href} className={styles.card}>
        <div>
          <h3 className={styles.title}>{title}</h3>
          {description ? <p className={styles.description}>{description}</p> : null}
        </div>
        <dl className={styles.stats}>
          {stats.map((stat) => (
            <div key={stat.label}>
              <dt>{stat.label}</dt>
              <dd>{stat.value}</dd>
            </div>
          ))}
        </dl>
        <div className={styles.meta}>
          <span>{meta}</span>
          <span className={styles.go} aria-hidden="true">
            Open →
          </span>
        </div>
      </Link>
    </li>
  );
}

/** The dashed "add" card at the end of a grid (prototype .pcard.add). */
export function AddCard({ href, label }: { href: string; label: string }) {
  return (
    <li className={styles.item}>
      <Link href={href} className={styles.add}>
        <span className={styles.plus} aria-hidden="true">
          +
        </span>
        <span>{label}</span>
      </Link>
    </li>
  );
}
