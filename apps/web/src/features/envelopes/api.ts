"use client";

import type { components } from "@signora/contracts";
import { useQuery } from "@tanstack/react-query";

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

export function useEnvelopes(departmentId: string, status: EnvelopeStatus | null) {
  return useQuery({
    queryKey: [...envelopesKey(departmentId), status],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/departments/{department_id}/envelopes", {
          params: { path: { department_id: departmentId }, query: status ? { status } : {} },
        }),
      ),
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
export type FormField = SendForm["fields"][number];
export type FormSigner = SendForm["signers"][number];
export type FormCountersigner = SendForm["countersigners"][number];
