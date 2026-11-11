"use client";

import Link from "next/link";
import { useState } from "react";

import { formError } from "@/shared/api/errors";
import { Heading1, LinkButton, Notice, SearchField, TextButton } from "@/shared/ui";

import { useWaiting, type InboxState, type Waiting } from "./api";
import styles from "./inbox.module.css";

const DAY = 86_400_000;
const SOON_DAYS = 3; // an expiry this close is said in the "waiting" orange
const SEARCH_FROM = 9; // a search box once the list is longer than a screen

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

function matches(item: Waiting, needle: string): boolean {
  return `${item.title} ${item.document_name} ${item.department_name} ${item.signers.join(" ")}`.toLowerCase().includes(needle);
}

/**
 * To countersign (Phase 8 §7.2): a table that holds up at any length. What waits for me, soonest
 * expiry first, each marked with the "waiting" orange; what I countersigned in its own tab, muted.
 * On a phone each row stacks into a block.
 */
export function CountersignInbox() {
  const [state, setState] = useState<InboxState>("waiting");
  const [query, setQuery] = useState("");
  const list = useWaiting(state);
  const [now] = useState(() => Date.now());
  const items = list.data?.pages.flatMap((page) => page.items) ?? [];
  const needle = query.trim().toLowerCase();
  const shown = needle ? items.filter((item) => matches(item, needle)) : items;
  const waiting = state === "waiting";

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
              onClick={() => {
                setState(one);
                setQuery("");
              }}
            >
              {one === "waiting" ? "Waiting for you" : "Countersigned"}
            </button>
          ))}
        </div>
        {items.length >= SEARCH_FROM ? (
          <SearchField label="Search" value={query} onChange={(event) => setQuery(event.target.value)} />
        ) : null}
      </div>

      {list.isError ? <Notice tone="warning">{formError(list.error)}</Notice> : null}
      {list.data && shown.length === 0 ? (
        <p className={styles.empty}>
          {needle ? "Nothing matches." : waiting ? "Nothing waits for your countersignature." : "You haven't countersigned anything yet."}
        </p>
      ) : null}

      {shown.length > 0 ? (
        <table className={waiting ? styles.table : `${styles.table} ${styles.muted}`}>
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
            {shown.map((item) => {
              const ends = expiry(item.expires_at, now);
              return (
                <tr key={item.recipient_id}>
                  <td className={styles.envelope}>
                    {waiting ? <span className={styles.dot} aria-label="Waiting for you" role="img" /> : null}
                    <span className={styles.names}>
                      <Link href={waiting ? `/countersign/${item.recipient_id}` : `/departments/${item.department_id}/envelopes/${item.envelope_id}`} className={styles.title}>
                        {item.document_name}
                      </Link>
                      <span className={styles.department}>{item.department_name}</span>
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
                    {waiting ? (
                      <LinkButton href={`/countersign/${item.recipient_id}`}>Countersign</LinkButton>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}

      {list.hasNextPage && !needle ? (
        <TextButton onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}>
          {list.isFetchingNextPage ? "Loading…" : "Show more"}
        </TextButton>
      ) : null}
    </main>
  );
}
