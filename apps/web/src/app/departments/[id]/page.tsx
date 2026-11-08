"use client";

import { useParams } from "next/navigation";

import { DepartmentPage } from "@/features/departments/DepartmentPage";
import { DocumentsSection } from "@/features/documents/DocumentsSection";
import { ConsoleShell } from "@/shared/session";

export default function DepartmentRoute() {
  const { id } = useParams<{ id: string }>();
  return (
    <ConsoleShell>
      {(me) => (
        <DepartmentPage
          me={me}
          id={id}
          documents={(department) => (
            <DocumentsSection
              departmentId={department.id}
              canEdit={department.access === "edit" && department.status === "active"}
            />
          )}
        />
      )}
    </ConsoleShell>
  );
}
