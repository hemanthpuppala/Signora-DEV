"use client";

import { useParams } from "next/navigation";

import { EnvelopePage } from "@/features/envelopes/EnvelopePage";
import { ConsoleShell } from "@/shared/session";

export default function EnvelopeRoute() {
  const { id, envelopeId } = useParams<{ id: string; envelopeId: string }>();
  return <ConsoleShell>{() => <EnvelopePage departmentId={id} envelopeId={envelopeId} />}</ConsoleShell>;
}
