"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { DepartmentPage } from "@/features/departments/DepartmentPage";
import { useDocuments } from "@/features/documents/api";
import { BatchProgress } from "@/features/envelopes/BatchProgress";
import { batchesKey } from "@/features/envelopes/bulkApi";
import { BulkSendModal } from "@/features/envelopes/BulkSendModal";
import { EnvelopesList } from "@/features/envelopes/EnvelopesList";
import { SendModal } from "@/features/envelopes/SendModal";
import { ConsoleShell } from "@/shared/session";
import { SmallText } from "@/shared/ui";

/**
 * A department opens on its envelopes (the prototype's screen 07). New envelope opens the send of
 * one; Send in bulk opens the send of many from a spreadsheet. Each dialog leads to the other.
 */
export default function DepartmentRoute() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [sending, setSending] = useState<"one" | "bulk" | null>(null);
  const documents = useDocuments(id);
  const editHref = (documentId: string) => `/departments/${id}/documents/${documentId}`;
  return (
    <ConsoleShell>
      {(me) => (
        <>
          <DepartmentPage
            me={me}
            id={id}
            tab="envelopes"
            documentCount={documents.data?.length}
            onAddEnvelope={() => setSending("one")}
            onSendInBulk={() => setSending("bulk")}
          >
            {(department) =>
              department.access === "edit" ? (
                <>
                  <BatchProgress departmentId={id} />
                  <EnvelopesList departmentId={id} />
                </>
              ) : (
                <SmallText>Envelopes and their clients&apos; details are for people who can send.</SmallText>
              )
            }
          </DepartmentPage>
          {sending === "one" && documents.data ? (
            <SendModal
              documents={documents.data}
              editHref={editHref}
              onClose={() => setSending(null)}
              onSent={(envelope) => router.push(`/departments/${id}/envelopes/${envelope.id}`)}
              onSendInBulk={() => setSending("bulk")}
            />
          ) : null}
          {sending === "bulk" && documents.data ? (
            <BulkSendModal
              documents={documents.data}
              editHref={editHref}
              onClose={() => setSending(null)}
              onSendOne={() => setSending("one")}
              onSent={() => {
                setSending(null);
                void queryClient.invalidateQueries({ queryKey: batchesKey(id) });
              }}
            />
          ) : null}
        </>
      )}
    </ConsoleShell>
  );
}
