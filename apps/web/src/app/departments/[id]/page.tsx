"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { useDirectory } from "@/features/departments/api";
import { DepartmentPage } from "@/features/departments/DepartmentPage";
import { useDocuments } from "@/features/documents/api";
import { SendModal } from "@/features/envelopes/SendModal";
import { ConsoleShell } from "@/shared/session";
import { SmallText } from "@/shared/ui";

/** A department opens on its envelopes (the prototype's project page); New envelope opens the send. */
export default function DepartmentRoute() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [sending, setSending] = useState(false);
  const documents = useDocuments(id);
  const directory = useDirectory();
  return (
    <ConsoleShell>
      {(me) => (
        <>
          <DepartmentPage
            me={me}
            id={id}
            tab="envelopes"
            documentCount={documents.data?.length}
            onAddEnvelope={() => setSending(true)}
          >
            {() => <SmallText>No envelopes yet. Envelopes sent from this department appear here.</SmallText>}
          </DepartmentPage>
          {sending && documents.data ? (
            <SendModal
              documents={documents.data}
              colleagues={directory.data ?? []}
              onClose={() => setSending(false)}
              onSent={(envelope) => router.push(`/departments/${id}/envelopes/${envelope.id}`)}
            />
          ) : null}
        </>
      )}
    </ConsoleShell>
  );
}
