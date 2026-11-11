"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { useDocuments } from "@/features/documents/api";
import { DocumentPage } from "@/features/documents/DocumentPage";
import { SendModal } from "@/features/envelopes/SendModal";
import { ConsoleShell } from "@/shared/session";

/** One document; "Send for signature" opens the send at its details, the document chosen (Phase 7 §2). */
export default function DocumentRoute() {
  const { id, documentId } = useParams<{ id: string; documentId: string }>();
  const router = useRouter();
  const [sending, setSending] = useState(false);
  const documents = useDocuments(id);
  return (
    <ConsoleShell width="full">
      {() => (
        <>
          <DocumentPage departmentId={id} documentId={documentId} onSend={() => setSending(true)} />
          {sending && documents.data ? (
            <SendModal
              documents={documents.data}
              initialDocumentId={documentId}
              onClose={() => setSending(false)}
              onSent={(envelope) => router.push(`/departments/${id}/envelopes/${envelope.id}`)}
            />
          ) : null}
        </>
      )}
    </ConsoleShell>
  );
}
