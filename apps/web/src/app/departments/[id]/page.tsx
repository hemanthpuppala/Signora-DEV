"use client";

import { useParams } from "next/navigation";

import { DepartmentPage } from "@/features/departments/DepartmentPage";
import { useDocuments } from "@/features/documents/api";
import { ConsoleShell } from "@/shared/session";
import { SmallText } from "@/shared/ui";

/** A department opens on its envelopes (the prototype's project page); sending comes in Phase 6. */
export default function DepartmentRoute() {
  const { id } = useParams<{ id: string }>();
  const documents = useDocuments(id);
  return (
    <ConsoleShell>
      {(me) => (
        <DepartmentPage me={me} id={id} tab="envelopes" documentCount={documents.data?.length}>
          {() => <SmallText>No envelopes yet. Envelopes sent from this department appear here.</SmallText>}
        </DepartmentPage>
      )}
    </ConsoleShell>
  );
}
