"use client";

import type { components } from "@signora/contracts";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/shared/api/client";
import type { Status } from "@/shared/ui";

export type SendRequest = components["schemas"]["SendRequest"];
export type Envelope = components["schemas"]["EnvelopeView"];
export type EnvelopeSummary = components["schemas"]["EnvelopeSummary"];
export type EnvelopeStatus = Envelope["status"];
export type Recipient = Envelope["recipients"][number];

export const envelopesKey = (departmentId: string) => ["envelopes", departmentId] as const;
export const envelopeKey = (id: string) => ["envelope", id] as const;

/** What sending a version asks (Phase 7 §2): only once a document and its approved version are chosen. */
export function useSendForm(documentId: string | null, versionId: string | null) {
  return useQuery({
    queryKey: ["send-form", documentId, versionId],
    enabled: documentId !== null && versionId !== null,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/documents/{document_id}/versions/{version_id}/send-form", {
          params: { path: { document_id: documentId ?? "", version_id: versionId ?? "" } },
        }),
      ),
  });
}

/**
 * An envelope's document as drawn: the sent version's pages and where each value goes. Its own
 * read, not the send form's: it is there after the document is archived.
 */
export function useEnvelopeDocument(envelopeId: string) {
  return useQuery({
    queryKey: [...envelopeKey(envelopeId), "document"],
    queryFn: () =>
      unwrap(api.GET("/api/v1/envelopes/{envelope_id}/document", { params: { path: { envelope_id: envelopeId } } })),
  });
}

/** A department's envelopes, newest first, 50 a page ("Show more" asks for the next). */
/** A department's envelopes: newest first, or with ``query`` the matching ones, best match first
 * (searched on the server by title, template, and each signer's name or email). */
export function useEnvelopes(departmentId: string, status: EnvelopeStatus | null, query = "") {
  return useInfiniteQuery({
    queryKey: [...envelopesKey(departmentId), status, query],
    placeholderData: keepPreviousData, // the last answer stays while the next one comes
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/departments/{department_id}/envelopes", {
          params: {
            path: { department_id: departmentId },
            query: {
              ...(status ? { status } : {}),
              ...(query ? { q: query } : {}),
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
}

export function useEnvelope(id: string) {
  return useQuery({
    queryKey: envelopeKey(id),
    queryFn: () => unwrap(api.GET("/api/v1/envelopes/{envelope_id}", { params: { path: { envelope_id: id } } })),
  });
}

/** An envelope's state in words, for its list and page (the pill shows the same state's tone). */
export const ENVELOPE_STATUS: Record<EnvelopeStatus, { label: string; pill: Status }> = {
  sent: { label: "Sent", pill: "sent" },
  opened: { label: "Opened", pill: "opened" },
  viewed: { label: "Read", pill: "viewed" },
  signed: { label: "Waiting on the firm", pill: "signed" },
  completed: { label: "Completed", pill: "completed" },
  declined: { label: "Declined", pill: "declined" },
  expired: { label: "Expired", pill: "expired" },
  cancelled: { label: "Withdrawn", pill: "cancelled" },
};

export const RECIPIENT_STATUS: Record<Recipient["status"], string> = {
  waiting: "Waiting",
  sent: "Sent",
  opened: "Opened",
  viewed: "Read",
  signed: "Signed",
  declined: "Declined",
};

// Types as the typed client returns them (it gives the API's 4-number tuples back as arrays).
export type SendForm = NonNullable<ReturnType<typeof useSendForm>["data"]>;
export type EnvelopeDocument = NonNullable<ReturnType<typeof useEnvelopeDocument>["data"]>;
export type FormField = SendForm["fields"][number];
export type FormSigner = SendForm["signers"][number];
export type FormCountersigner = SendForm["countersigners"][number];
