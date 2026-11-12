"use client";

import { useParams } from "next/navigation";

import { DepartmentPage } from "@/features/departments/DepartmentPage";
import { useDocuments } from "@/features/documents/api";
import { BatchProgress } from "@/features/envelopes/BatchProgress";
import { EnvelopesList } from "@/features/envelopes/EnvelopesList";
import { ConsoleShell } from "@/shared/session";
import { SmallText } from "@/shared/ui";

import { useDepartmentFollows } from "./_follow";
import { useDepartmentSending } from "./_sending";

/**
 * A department opens on its envelopes (the prototype's screen 07). New envelope and Send in bulk
 * are the department's, the same on every tab (``useDepartmentSending``).
 */
export default function DepartmentRoute() {
  const { id } = useParams<{ id: string }>();
  const documents = useDocuments(id);
  const sending = useDepartmentSending(id, documents.data);
  useDepartmentFollows(documents.data);
  return (
    <ConsoleShell>
      {(me) => (
        <>
          <DepartmentPage
            me={me}
            id={id}
            tab="envelopes"
            documentCount={documents.data?.length}
            onAddEnvelope={sending.onAddEnvelope}
            onSendInBulk={sending.onSendInBulk}
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
          {sending.dialogs}
        </>
      )}
    </ConsoleShell>
  );
}
