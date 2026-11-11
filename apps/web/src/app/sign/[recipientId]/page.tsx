"use client";

import { useParams } from "next/navigation";

import { SignerPage } from "@/features/signing/SignerPage";

export default function SignerRoute() {
  const { recipientId } = useParams<{ recipientId: string }>();
  return <SignerPage recipientId={recipientId} />;
}
