"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Notice, TextButton } from "@/shared/ui";

import { envelopesKey } from "./api";
import styles from "./bulk.module.css";
import { useBatches, type Batch } from "./bulkApi";

const DISMISSED = "signora:batches-dismissed";

function dismissedIds(): string[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.sessionStorage.getItem(DISMISSED) ?? "[]") as string[];
  } catch {
    return [];
  }
}

function summary(batch: Batch): string {
  const settled = batch.sent + batch.failed;
  if (batch.status === "sending") return `Sending ${settled.toLocaleString()} of ${batch.total.toLocaleString()} envelopes`;
  if (batch.failed === 0) return `${batch.sent.toLocaleString()} ${batch.sent === 1 ? "envelope" : "envelopes"} sent`;
  return `${batch.sent.toLocaleString()} sent, ${batch.failed.toLocaleString()} could not be sent`;
}

/**
 * A department's bulk sends (Bulk send §9): how far each has got while it is sending, then what
 * became of it, with the rows that could not be sent and why. A finished one can be dismissed.
 * The envelopes list is read again as envelopes go out.
 */
export function BatchProgress({ departmentId }: { departmentId: string }) {
  const batches = useBatches(departmentId);
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState<readonly string[]>(dismissedIds);

  // As envelopes go out, the list under this shows them.
  const sent = (batches.data?.batches ?? []).reduce((count, batch) => count + batch.sent, 0);
  const seen = useRef(sent);
  useEffect(() => {
    if (sent === seen.current) return;
    seen.current = sent;
    void queryClient.invalidateQueries({ queryKey: envelopesKey(departmentId) });
  }, [sent, departmentId, queryClient]);

  const shown = (batches.data?.batches ?? []).filter((batch) => !dismissed.includes(batch.id));
  if (shown.length === 0) return null;
  const dismiss = (id: string) => {
    const next = [...dismissed, id];
    setDismissed(next);
    try {
      window.sessionStorage.setItem(DISMISSED, JSON.stringify(next));
    } catch {
      // Private browsing: it stays dismissed for this visit.
    }
  };
  return (
    <div className={styles.batches} aria-live="polite">
      {shown.map((batch) => (
        <Notice
          key={batch.id}
          tone={batch.failed > 0 ? "warning" : "info"}
          title={`${summary(batch)} · ${batch.document_name}`}
          action={
            batch.status === "finished" ? <TextButton onClick={() => dismiss(batch.id)}>Dismiss</TextButton> : null
          }
        >
          {`From ${batch.file_name}.`}
          {batch.failures.length > 0 ? (
            <ul className={styles.failures}>
              {batch.failures.map((failure) => (
                <li key={failure.row_no}>{`Row ${failure.row_no} · ${failure.label}: ${failure.error}`}</li>
              ))}
            </ul>
          ) : null}
        </Notice>
      ))}
    </div>
  );
}
