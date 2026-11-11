"use client";

import Link from "next/link";

import { formError } from "@/shared/api/errors";
import { BodyText, Heading1, Notice } from "@/shared/ui";

import { useWaiting } from "./api";
import styles from "./signing.module.css";

function day(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** To countersign (Phase 8 §7.2): every envelope waiting for me, across my departments. */
export function CountersignInbox() {
  const waiting = useWaiting();
  return (
    <main className={styles.inbox}>
      <Heading1>To countersign</Heading1>
      {waiting.isError ? <Notice tone="warning">{formError(waiting.error)}</Notice> : null}
      {waiting.data && waiting.data.items.length === 0 ? <BodyText>Nothing to countersign.</BodyText> : null}
      <ul className={styles.rows}>
        {waiting.data?.items.map((item) => (
          <li key={item.recipient_id} className={styles.row}>
            <Link href={`/countersign/${item.recipient_id}`} className={styles.rowLink}>
              <span className={styles.rowTitle}>{item.title}</span>
              <span className={styles.rowMeta}>
                {[item.department_name, item.document_name, `Signed by ${item.signers.join(", ")}`, item.signed_at ? `Last signed ${day(item.signed_at)}` : null, `Expires ${day(item.expires_at)}`]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
