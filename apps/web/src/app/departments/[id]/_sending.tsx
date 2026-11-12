"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { batchesKey } from "@/features/envelopes/bulkApi";
import { BulkSendModal } from "@/features/envelopes/BulkSendModal";
import { SendModal, type SendableDocument } from "@/features/envelopes/SendModal";

/**
 * A department's two ways to send, the same from every tab: New envelope (one template to its
 * people) and Send in bulk (one template to many, from a spreadsheet); each dialog leads to the
 * other. One home for both tabs, as the routes own the dialogs (a feature never imports another).
 * A bulk send's progress is on the Envelopes tab, so one started elsewhere goes there.
 */
export function useDepartmentSending(
  id: string,
  documents: readonly SendableDocument[] | undefined,
): { onAddEnvelope: () => void; onSendInBulk: () => void; dialogs: ReactNode } {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const [sending, setSending] = useState<"one" | "bulk" | null>(null);
  const envelopes = `/departments/${id}`;
  const editHref = (documentId: string) => `/departments/${id}/documents/${documentId}`;

  const dialogs =
    sending === "one" && documents ? (
      <SendModal
        documents={documents}
        editHref={editHref}
        onClose={() => setSending(null)}
        onSent={(envelope) => router.push(`/departments/${id}/envelopes/${envelope.id}`)}
        onSendInBulk={() => setSending("bulk")}
      />
    ) : sending === "bulk" && documents ? (
      <BulkSendModal
        documents={documents}
        editHref={editHref}
        onClose={() => setSending(null)}
        onSendOne={() => setSending("one")}
        onSent={() => {
          setSending(null);
          void queryClient.invalidateQueries({ queryKey: batchesKey(id) });
          if (pathname !== envelopes) router.push(envelopes);
        }}
      />
    ) : null;

  return { onAddEnvelope: () => setSending("one"), onSendInBulk: () => setSending("bulk"), dialogs };
}
