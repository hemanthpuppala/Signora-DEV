"use client";

import { useParams } from "next/navigation";

import { DepartmentPage } from "@/features/departments/DepartmentPage";
import { useDocuments } from "@/features/documents/api";
import { DocumentsSection } from "@/features/documents/DocumentsSection";
import { ConsoleShell } from "@/shared/session";
import { HeadAction } from "@/shared/ui";

/** A department's Documents tab: its documents as cards, and Upload document for editors. */
export default function DepartmentDocumentsRoute() {
  const { id } = useParams<{ id: string }>();
  const documents = useDocuments(id);
  return (
    <ConsoleShell>
      {(me) => (
        <DepartmentPage
          me={me}
          id={id}
          tab="documents"
          documentCount={documents.data?.length}
          tabActions={(department) =>
            department.access === "edit" && department.status === "active" ? (
              <HeadAction icon="upload" label="Upload document" href={`/departments/${id}/upload`} />
            ) : null
          }
        >
          {(department) => (
            <DocumentsSection
              departmentId={department.id}
              canEdit={department.access === "edit" && department.status === "active"}
            />
          )}
        </DepartmentPage>
      )}
    </ConsoleShell>
  );
}
