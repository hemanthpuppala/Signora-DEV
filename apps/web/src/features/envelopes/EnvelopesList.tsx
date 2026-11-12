"use client";

import Link from "next/link";
import { useState } from "react";

import { formError } from "@/shared/api/errors";
import { SEARCH_SETTLE_MS, useDebounced } from "@/shared/lib/useDebounced";
import { Button, Chip, ChipGroup, ListControls, Notice, SearchField, SmallText, StatusPill, TablePanel, TextButton } from "@/shared/ui";

import { ENVELOPE_STATUS, useEnvelopes, type EnvelopeStatus } from "./api";
import styles from "./envelopes.module.css";

const FILTERS: readonly (EnvelopeStatus | null)[] = [null, "sent", "viewed", "signed", "completed", "declined", "expired", "cancelled"];

/** "Nov 9" (this year) or "Nov 9, 2025". */
export function day(iso: string): string {
  const date = new Date(iso);
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) });
}

/**
 * A department's envelopes (Phase 7 §6; the prototype's screen 07): newest first, filtered by state,
 * each row opening its envelope. The signers' names and how many have signed say where it stands.
 * A search (on the server: the customer's name or email, the template or the title) puts the best
 * match first.
 */
export function EnvelopesList({ departmentId }: { departmentId: string }) {
  const [status, setStatus] = useState<EnvelopeStatus | null>(null);
  const [typed, setTyped] = useState("");
  const query = useDebounced(typed.trim(), SEARCH_SETTLE_MS);
  const envelopes = useEnvelopes(departmentId, status, query);
  const rows = envelopes.data?.pages.flatMap((page) => page.envelopes) ?? [];

  if (envelopes.isError) return <Notice tone="warning">{formError(envelopes.error)}</Notice>;
  return (
    <div className={styles.steps}>
      <ListControls
        search={
          <SearchField label="Search by customer, email or template" value={typed} onChange={(event) => setTyped(event.target.value)} />
        }
      />
      <ChipGroup label="Show envelopes">
        {FILTERS.map((filter) => (
          <Chip key={filter ?? "all"} selected={status === filter} onClick={() => setStatus(filter)}>
            {filter ? ENVELOPE_STATUS[filter].label : "All"}
          </Chip>
        ))}
      </ChipGroup>
      <div role="status" aria-live="polite">
        {envelopes.isSuccess && !envelopes.isPlaceholderData && rows.length === 0 ? (
          query ? (
            <SmallText>
              {`No envelope matches “${query}”${status ? " in this state" : ""}. `}
              <TextButton onClick={() => setTyped("")}>Clear search</TextButton>
            </SmallText>
          ) : (
            <SmallText>{status ? "No envelopes in this state." : "No envelopes yet. Send one with New envelope above."}</SmallText>
          )
        ) : null}
      </div>
      {rows.length > 0 ? (
        <TablePanel label="Envelopes">
          <table>
            <thead>
              <tr>
                <th>Envelope</th>
                <th>Signers</th>
                <th>Status</th>
                <th>Sent</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((envelope) => (
                <tr key={envelope.id}>
                  <td>
                    <Link href={`/departments/${departmentId}/envelopes/${envelope.id}`} className={styles.rowLink}>
                      {envelope.title}
                    </Link>
                    <span className={styles.sub}>{`${envelope.document_name} · v${envelope.version_number}`}</span>
                  </td>
                  <td>
                    {envelope.signers.join(", ")}
                    <span className={styles.sub}>{`${envelope.signed} of ${envelope.signers.length} signed`}</span>
                  </td>
                  <td>
                    <StatusPill status={ENVELOPE_STATUS[envelope.status].pill} label={ENVELOPE_STATUS[envelope.status].label} />
                  </td>
                  <td>
                    {day(envelope.sent_at)}
                    <span className={styles.sub}>{`expires ${day(envelope.expires_at)}`}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TablePanel>
      ) : null}
      {envelopes.hasNextPage ? (
        <div>
          <Button variant="quiet" compact loading={envelopes.isFetchingNextPage} loadingLabel="Loading…" onClick={() => void envelopes.fetchNextPage()}>
            Show more
          </Button>
        </div>
      ) : null}
    </div>
  );
}
