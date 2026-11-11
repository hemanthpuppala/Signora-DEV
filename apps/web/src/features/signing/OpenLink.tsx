"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthPanel } from "@/shared/ui";

import { openLink, type Opened } from "./api";
import { SignerProblem } from "./SignerNotices";

// One exchange per token per page load: effects can run twice (strict mode, a remount), and the
// second run must reuse the first answer, not open again.
const exchanges = new Map<string, Promise<Opened>>();

/**
 * `/s/{token}` (Phase 8 §1.1): a deliberate request, so a mail scanner that only loads the page
 * opens nothing; then the clean address `/sign/{recipient}`, so the token leaves the address bar
 * and the history.
 */
export function OpenLink({ token }: { token: string }) {
  const router = useRouter();
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let exchange = exchanges.get(token);
    if (!exchange) {
      exchange = openLink(token);
      exchanges.set(token, exchange);
    }
    exchange.then(
      (opened) => router.replace(`/sign/${opened.recipient_id}`),
      (failure: unknown) => setError(failure),
    );
  }, [router, token]);
  if (error) return <SignerProblem error={error} />;
  return (
    <AuthPanel eyebrow="Signing" heading="Opening your document…">
      {null}
    </AuthPanel>
  );
}

/** Tests only. */
export function forgetExchangesForTests(): void {
  exchanges.clear();
}
