"use client";

import Link from "next/link";
import { useState } from "react";

import { formError } from "@/shared/api/errors";
import { SEARCH_SETTLE_MS, useDebounced } from "@/shared/lib/useDebounced";
import { Heading1, LinkButton, Notice, SearchField, Select, TextButton } from "@/shared/ui";

import { useWaiting, type InboxState } from "./api";
import styles from "./inbox.module.css";

const DAY = 86_400_000;
const ALL = "all"; // the department choice that filters nothing
const SOON_DAYS = 3; // an expiry this close is said in the "waiting" orange

function day(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** "today", "1 day", "5 days": how long something has waited. */
function waited(iso: string | null, now: number): string {
  if (!iso) return "";
  const days = Math.floor((now - Date.parse(iso)) / DAY);
  return days <= 0 ? "Today" : days === 1 ? "1 day" : `${days} days`;
}

/** "in 2 days" (soon: true), or the date. */
function expiry(iso: string, now: number): { words: string; soon: boolean } {
  const days = Math.ceil((Date.parse(iso) - now) / DAY);
  if (days <= SOON_DAYS) return { words: days <= 1 ? "Within a day" : `In ${days} days`, soon: true };
  return { words: day(iso), soon: false };
}

/**
 * To countersign (Phase 8 §7.2): a table that holds up at any length. What waits for me, soonest
 * expiry first, each marked with the "waiting" orange; what I countersigned in its own tab, muted.
 * On a phone each row stacks into a block.
 */
export function CountersignInbox() {
  const [state, setState] = useState<InboxState>("waiting");
  const [typed, setTyped] = useState("");
  const query = useDebounced(typed.trim(), SEARCH_SETTLE_MS);
  const [department, setDepartment] = useState<string | null>(null); // null: every department
  const list = useWaiting(state, query, department);
  const [now] = useState(() => Date.now());
  const first = list.data?.pages[0];
  const items = list.data?.pages.flatMap((page) => page.items) ?? [];
  const waiting = state === "waiting";
  const counts = { waiting: first?.waiting, done: first?.done };
  const total = first?.total ?? 0;
  // The departments they countersign in; a choice only when there is more than one.
  const departments = first?.departments ?? [];

  const quiet = (words: string) => (
    <tr>
      <td colSpan={5} className={styles.emptyRow}>
        {words}
      </td>
    </tr>
  );

  return (
    <main className={styles.page}>
      <Heading1>To countersign</Heading1>
      <div className={styles.controls}>
        <div className={styles.tabs} role="tablist" aria-label="Countersigning">
          {(["waiting", "done"] as const).map((one) => (
            <button
              key={one}
              type="button"
              role="tab"
              aria-selected={state === one}
              className={styles.tab}
              onClick={() => setState(one)}
            >
              {one === "waiting" ? "Waiting for you" : "Countersigned"}
              {counts[one] !== undefined ? <span className={styles.tabCount}>{` · ${counts[one]}`}</span> : null}
            </button>
          ))}
        </div>
        <div className={styles.filters}>
          {departments.length > 1 || department ? (
            <Select
              label="Department"
              labelHidden
              className={styles.department ?? ""}
              options={[{ value: ALL, label: "All departments" }, ...departments.map((d) => ({ value: d.id, label: d.name }))]}
              value={department ?? ALL}
              onChange={(value) => setDepartment(value === ALL ? null : value)}
            />
          ) : null}
          <SearchField label="Search by customer, email or template" value={typed} onChange={(event) => setTyped(event.target.value)} />
        </div>
      </div>

      {list.isError ? <Notice tone="warning">{formError(list.error)}</Notice> : null}

      <table className={waiting ? styles.table : `${styles.table} ${styles.muted}`}>
        <colgroup>
          <col className={styles.colEnvelope} />
          <col className={styles.colSigners} />
          <col className={styles.colWhen} />
          <col className={styles.colWhen} />
          <col className={styles.colAction} />
        </colgroup>
        <thead>
          <tr>
            <th scope="col">Envelope</th>
            <th scope="col">Signed by</th>
            <th scope="col">{waiting ? "Waiting" : "Countersigned"}</th>
            <th scope="col">{waiting ? "Expires" : "Copy"}</th>
            <th scope="col">
              <span className={styles.hidden}>Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {!list.data && !list.isError ? quiet("Loading…") : null}
          {list.data && items.length === 0
            ? quiet(query ? "Nothing matches your search." : waiting ? "Nothing waits for your countersignature." : "You haven't countersigned anything yet.")
            : null}
          {items.map((item) => {
            const ends = expiry(item.expires_at, now);
            return (
              <tr key={item.recipient_id}>
                <td>
                  <span className={styles.envelope}>
                    {waiting ? <span className={styles.dot} aria-label="Waiting for you" role="img" /> : null}
                    <span className={styles.names}>
                      <Link
                        href={waiting ? `/countersign/${item.recipient_id}` : `/departments/${item.department_id}/envelopes/${item.envelope_id}`}
                        className={styles.title}
                      >
                        {item.document_name}
                      </Link>
                      <span className={styles.department}>{item.department_name}</span>
                    </span>
                  </span>
                </td>
                <td data-label="Signed by">{item.signers.join(", ")}</td>
                <td data-label={waiting ? "Waiting" : "Countersigned"}>
                  {waiting ? waited(item.signed_at, now) : item.countersigned_at ? day(item.countersigned_at) : ""}
                </td>
                <td data-label={waiting ? "Expires" : "Copy"} className={waiting && ends.soon ? styles.soon : undefined}>
                  {waiting ? ends.words : item.completed ? "Completed" : "Being made"}
                </td>
                <td className={styles.action}>
                  {waiting ? <LinkButton href={`/countersign/${item.recipient_id}`}>Countersign</LinkButton> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className={styles.footer}>
        {total > 0 ? <span>{`Showing ${items.length} of ${total}`}</span> : <span />}
        {list.hasNextPage ? (
          <TextButton onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}>
            {list.isFetchingNextPage ? "Loading…" : "Show more"}
          </TextButton>
        ) : null}
      </div>
    </main>
  );
}
