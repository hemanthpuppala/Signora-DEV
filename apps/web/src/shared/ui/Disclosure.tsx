import type { ReactNode } from "react";

import { Icon } from "./Icon";
import styles from "./disclosure.module.css";

/**
 * A titled group that opens and closes in place (an envelope's signers, its countersigners): the
 * title as a quiet label with how many it holds and a chevron, the content under it. A native
 * ``<details>``, so it opens by keyboard and is announced as expanded or collapsed with no script.
 * Open to begin with unless ``defaultOpen`` is false; it then keeps what the person chose.
 */
export function Disclosure({
  title,
  count,
  defaultOpen = true,
  children,
}: {
  title: string;
  count?: number | undefined;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details className={styles.disclosure} open={defaultOpen}>
      <summary className={styles.summary}>
        <span className={styles.title}>{title}</span>
        {count !== undefined ? <span className={styles.count}>{count}</span> : null}
        <Icon name="chevron" size={14} className={styles.chevron} />
      </summary>
      <div className={styles.body}>{children}</div>
    </details>
  );
}
