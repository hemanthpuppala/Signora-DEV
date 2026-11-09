"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";

import type { Department } from "@/features/departments/api";
import { NewDepartmentForm } from "@/features/departments/NewDepartmentForm";
import { handOff } from "@/features/documents/api";
import { useDocumentLimits } from "@/features/documents/limits";
import { can, ConsoleShell } from "@/shared/session";

export default function NewDepartmentPage() {
  const router = useRouter();
  const limits = useDocumentLimits();
  // A held file goes to the new department's upload page, which uploads it (Phase 4 LLD §6.3).
  const onCreated = useCallback(
    (department: Department, file: File | null) => {
      if (!file) {
        router.replace(`/departments/${department.id}`);
        return;
      }
      handOff(department.id, file);
      router.replace(`/departments/${department.id}/upload`);
    },
    [router],
  );
  return (
    <ConsoleShell requires="departments.create">
      {(me) => (
        <NewDepartmentForm
          onCreated={onCreated}
          upload={can(me, "documents.send") ? { hint: limits.hint } : undefined}
        />
      )}
    </ConsoleShell>
  );
}
