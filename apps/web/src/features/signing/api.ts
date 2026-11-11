import { useQuery } from "@tanstack/react-query";

import type { components } from "@signora/contracts";

import { api, unwrap } from "@/shared/api/client";

export type Opened = components["schemas"]["Opened"];
export type SignerState = components["schemas"]["SignerState"];

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
