"use client";

import { useParams } from "next/navigation";

import { DepartmentSettings } from "@/features/departments/DepartmentSettings";
import { ConsoleShell } from "@/shared/session";

export default function DepartmentSettingsRoute() {
  const { id } = useParams<{ id: string }>();
  return (
    <ConsoleShell requires="departments.manage">{(me) => <DepartmentSettings me={me} id={id} />}</ConsoleShell>
  );
}
