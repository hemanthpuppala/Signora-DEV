import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import type { components } from "@signora/contracts";

import { api, unwrap } from "@/shared/api/client";

export type Opened = components["schemas"]["Opened"];
export type SignerState = components["schemas"]["SignerState"];
/** As the API answers it (the schema of the response, where a place's rect is a plain list). */
export type SignerDocument = NonNullable<ReturnType<typeof useSignerDocument>["data"]>;
export type SignerField = SignerDocument["fields"][number];

/** Exchange the emailed link's token for this browser's signing session (Phase 8 §1.1.1). */
export const openLink = (token: string) =>
  unwrap(api.POST("/api/v1/sign/open", { body: { token } }));

export const signerKey = (recipientId: string) => ["signer", recipientId] as const;

export function useSigner(recipientId: string) {
  return useQuery({
    queryKey: signerKey(recipientId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/sign/{recipient_id}", { params: { path: { recipient_id: recipientId } } }),
      ),
    retry: false, // a closed link or an ended session is an answer, not a failure to retry
  });
}

export type CodeSent = components["schemas"]["CodeSentView"];

export const sendCode = (recipientId: string, again: boolean) =>
  unwrap(
    api.POST("/api/v1/sign/{recipient_id}/code", {
      params: { path: { recipient_id: recipientId } },
      body: { again },
    }),
  );

export const verifyCode = (recipientId: string, code: string) =>
  unwrap(
    api.POST("/api/v1/sign/{recipient_id}/verify", {
      params: { path: { recipient_id: recipientId } },
      body: { code },
    }),
  );

export const giveConsent = (recipientId: string, version: string) =>
  unwrap(
    api.POST("/api/v1/sign/{recipient_id}/consent", {
      params: { path: { recipient_id: recipientId } },
      body: { disclosure_version: version },
    }),
  );

export const documentKey = (recipientId: string) => ["signer", recipientId, "document"] as const;

export function useSignerDocument(recipientId: string) {
  return useQuery({
    queryKey: documentKey(recipientId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/sign/{recipient_id}/document", {
          params: { path: { recipient_id: recipientId } },
        }),
      ),
    retry: false,
  });
}

export const saveDraft = (recipientId: string, fieldId: string, value: string) =>
  unwrap(
    api.PUT("/api/v1/sign/{recipient_id}/drafts/{field_id}", {
      params: { path: { recipient_id: recipientId, field_id: fieldId } },
      body: { value },
    }),
  );

export const clearDraft = (recipientId: string, fieldId: string) =>
  unwrap(
    api.DELETE("/api/v1/sign/{recipient_id}/drafts/{field_id}", {
      params: { path: { recipient_id: recipientId, field_id: fieldId } },
    }),
  );

export const markViewed = (recipientId: string) =>
  unwrap(
    api.POST("/api/v1/sign/{recipient_id}/viewed", {
      params: { path: { recipient_id: recipientId } },
    }),
  );

export const pdfUrl = (recipientId: string) => `/api/v1/sign/${recipientId}/pdf`;

/** As the API answers it (a stroke's points are plain lists there). */
export type Adopted = NonNullable<ReturnType<typeof useSignature>["data"]>["adopted"][number];
export type SignatureIn = components["schemas"]["SignatureIn"];
export const signatureKey = (recipientId: string) => ["signer", recipientId, "signature"] as const;

export function useSignature(recipientId: string) {
  return useQuery({
    queryKey: signatureKey(recipientId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/sign/{recipient_id}/signature", {
          params: { path: { recipient_id: recipientId } },
        }),
      ),
    retry: false,
  });
}

export const adoptSignature = (recipientId: string, kind: Adopted["kind"], body: SignatureIn) =>
  unwrap(
    api.PUT("/api/v1/sign/{recipient_id}/signature/{kind}", {
      params: { path: { recipient_id: recipientId, kind } },
      body,
    }),
  );

export const applyToAll = (recipientId: string, kind: Adopted["kind"]) =>
  unwrap(
    api.POST("/api/v1/sign/{recipient_id}/apply-all/{kind}", {
      params: { path: { recipient_id: recipientId, kind } },
    }),
  );

export const submitSigning = (recipientId: string, key: string) =>
  unwrap(
    api.POST("/api/v1/sign/{recipient_id}/submit", {
      params: { path: { recipient_id: recipientId } },
      headers: { "Idempotency-Key": key },
    }),
  );

export const declineSigning = (recipientId: string, reason: string, key: string) =>
  unwrap(
    api.POST("/api/v1/sign/{recipient_id}/decline", {
      params: { path: { recipient_id: recipientId } },
      body: { reason },
      headers: { "Idempotency-Key": key },
    }),
  );

export type InboxState = "waiting" | "done";
export type Waiting = NonNullable<ReturnType<typeof useWaiting>["data"]>["pages"][number]["items"][number];

/** My countersigning (Phase 8 §7.2): what waits for me, or what I countersigned; pages of 50. */
export function useWaiting(state: InboxState, q: string, department: string | null = null) {
  return useInfiniteQuery({
    queryKey: ["me", "countersign", state, q, department],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/me/countersign", {
          params: {
            query: {
              state,
              ...(q ? { q } : {}),
              ...(department ? { department } : {}),
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    refetchOnWindowFocus: true,
  });
}

export function useDone(recipientId: string) {
  return useQuery({
    queryKey: ["signer", recipientId, "done"],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/sign/{recipient_id}/done", {
          params: { path: { recipient_id: recipientId } },
        }),
      ),
    retry: false,
  });
}

export const copyUrl = (recipientId: string) => `/api/v1/sign/${recipientId}/copy.pdf`;

/** A completed envelope's copy, for the colleague who countersigned it (Phase 8 §9.1). */
export const completedUrl = (recipientId: string, part: "combined" | "document" | "certificate") =>
  `/api/v1/sign/${recipientId}/completed?part=${part}`;
