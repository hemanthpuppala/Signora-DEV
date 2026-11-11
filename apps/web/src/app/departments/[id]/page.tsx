"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { DepartmentPage } from "@/features/departments/DepartmentPage";
import { useDocuments } from "@/features/documents/api";
import { EnvelopesList } from "@/features/envelopes/EnvelopesList";
import { SendModal } from "@/features/envelopes/SendModal";
import { ConsoleShell } from "@/shared/session";
import { SmallText } from "@/shared/ui";

/** A department opens on its envelopes (the prototype's screen 07); New envelope opens the send. */
export default function DepartmentRoute() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [sending, setSending] = useState(false);
  const documents = useDocuments(id);
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
            {(department) =>
              department.access === "edit" ? (
                <EnvelopesList departmentId={id} />
              ) : (
                <SmallText>Envelopes and their clients&apos; details are for people who can send.</SmallText>
              )
            }
          </DepartmentPage>
          {sending && documents.data ? (
            <SendModal
              documents={documents.data}
              editHref={(documentId) => `/departments/${id}/documents/${documentId}`}
              onClose={() => setSending(false)}
              onSent={(envelope) => router.push(`/departments/${id}/envelopes/${envelope.id}`)}
            />
          ) : null}
        </>
      )}
    </ConsoleShell>
  );
}
