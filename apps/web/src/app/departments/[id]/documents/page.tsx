"use client";

import { useParams } from "next/navigation";

import { DepartmentPage } from "@/features/departments/DepartmentPage";
import { useDocuments } from "@/features/documents/api";
import { DocumentsSection } from "@/features/documents/DocumentsSection";
import { ConsoleShell } from "@/shared/session";

/** A department's Templates tab: its templates as cards (Upload template is in the department's head). */
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
