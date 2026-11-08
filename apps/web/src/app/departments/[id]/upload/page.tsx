"use client";

import { useParams } from "next/navigation";

import { useDepartment } from "@/features/departments/api";
import { UploadPage } from "@/features/documents/UploadPage";
import { formError } from "@/shared/api/errors";
import { ConsoleShell } from "@/shared/session";
import { Notice } from "@/shared/ui";

function Upload({ id }: { id: string }) {
  const department = useDepartment(id);
  if (department.isError) return <Notice tone="warning">{formError(department.error)}</Notice>;
  const data = department.data;
  if (!data) return null;
  return <UploadPage department={{ id: data.id, name: data.name, status: data.status, access: data.access }} />;
}

export default function UploadRoute() {
  const { id } = useParams<{ id: string }>();
  return <ConsoleShell>{() => <Upload id={id} />}</ConsoleShell>;
}
