"use client";

import { useParams } from "next/navigation";

import { DocumentPage } from "@/features/documents/DocumentPage";
import { ConsoleShell } from "@/shared/session";

export default function DocumentRoute() {
  const { id, documentId } = useParams<{ id: string; documentId: string }>();
  return <ConsoleShell>{() => <DocumentPage departmentId={id} documentId={documentId} />}</ConsoleShell>;
}
