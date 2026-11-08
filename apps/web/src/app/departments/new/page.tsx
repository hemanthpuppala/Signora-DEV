"use client";

import { NewDepartmentForm } from "@/features/departments/NewDepartmentForm";
import { ConsoleShell } from "@/shared/session";

export default function NewDepartmentPage() {
  return <ConsoleShell requires="departments.create">{() => <NewDepartmentForm />}</ConsoleShell>;
}
