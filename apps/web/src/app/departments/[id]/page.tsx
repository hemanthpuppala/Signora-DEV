"use client";

import { useParams } from "next/navigation";

import { DepartmentPage } from "@/features/departments/DepartmentPage";
import { ConsoleShell } from "@/shared/session";

export default function DepartmentRoute() {
  const { id } = useParams<{ id: string }>();
  return <ConsoleShell>{(me) => <DepartmentPage me={me} id={id} />}</ConsoleShell>;
}
