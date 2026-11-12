"use client";

import { useParams } from "next/navigation";

import { DepartmentPage } from "@/features/departments/DepartmentPage";
import { useDocuments } from "@/features/documents/api";
import { DocumentsSection } from "@/features/documents/DocumentsSection";
import { ConsoleShell } from "@/shared/session";

import { useDepartmentFollows } from "../_follow";
import { useDepartmentSending } from "../_sending";

/** A department's Templates tab: its templates as cards, with the department's actions as on every tab. */
export default function DepartmentDocumentsRoute() {
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
            tab="documents"
            documentCount={documents.data?.length}
            onAddEnvelope={sending.onAddEnvelope}
            onSendInBulk={sending.onSendInBulk}
          >
            {(department) => (
              <DocumentsSection
                departmentId={department.id}
                canEdit={department.access === "edit" && department.status === "active"}
              />
            )}
          </DepartmentPage>
          {sending.dialogs}
        </>
      )}
    </ConsoleShell>
  );
}
