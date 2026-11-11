"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { useDocuments } from "@/features/documents/api";
import { EnvelopePage } from "@/features/envelopes/EnvelopePage";
import { SendModal, type SendDraft } from "@/features/envelopes/SendModal";
import { ConsoleShell } from "@/shared/session";

/** An envelope; a declined one can be sent again, from the same draft (Phase 8 §8.1.4). */
export default function EnvelopeRoute() {
  const { id, envelopeId } = useParams<{ id: string; envelopeId: string }>();
  const router = useRouter();
  const [again, setAgain] = useState<SendDraft | null>(null);
  const documents = useDocuments(id);
  return (
    <ConsoleShell width="full">
      {() => (
        <>
          <EnvelopePage departmentId={id} envelopeId={envelopeId} onSendAgain={setAgain} />
          {again ? (
            <SendModal
              documents={documents.data ?? []}
              initial={again}
              editHref={(documentId) => `/departments/${id}/documents/${documentId}`}
              onClose={() => setAgain(null)}
              onSent={(envelope) => {
                setAgain(null);
                router.push(`/departments/${id}/envelopes/${envelope.id}`);
              }}
            />
          ) : null}
        </>
      )}
    </ConsoleShell>
  );
}
