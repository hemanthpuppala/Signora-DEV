"use client";

import { Suspense } from "react";

import { DepartmentsHome } from "@/features/departments/DepartmentsHome";
import { ConsoleShell } from "@/shared/session";

/** Console home: the company's departments. */
export default function DepartmentsPage() {
  return (
    <ConsoleShell>
      {(me) => (
        <Suspense>
          <DepartmentsHome me={me} />
        </Suspense>
      )}
    </ConsoleShell>
  );
}
