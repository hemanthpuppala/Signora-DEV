"use client";

import { useParams } from "next/navigation";

import { SignerPage } from "@/features/signing/SignerPage";

/**
 * A countersigner signs signed in (Phase 8 §7.1.2): the request proxy sends a signed-out visitor to
 * log in and back; the API checks the session is the designated colleague's. The page is the
 * signer's own screen, so it stands alone like theirs.
 */
export default function CountersignOneRoute() {
  const { recipientId } = useParams<{ recipientId: string }>();
  return <SignerPage recipientId={recipientId} />;
}
