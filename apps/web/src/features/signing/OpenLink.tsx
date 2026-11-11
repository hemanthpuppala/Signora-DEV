"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthPanel, Button } from "@/shared/ui";

import { openLink } from "./api";
import { SignerProblem } from "./SignerNotices";

/**
 * `/s/{token}` (Phase 8 §1.1): the link is opened by the person's own press, never by the page
 * loading. Link-safety services fetch every link in an email and many run its script in a
 * headless browser, but none presses a button, so a scan opens no session, records no "opened"
 * and sends no email code. Then the clean address `/sign/{recipient}`, so the token leaves the
 * address bar and the history.
 */
export function OpenLink({ token }: { token: string }) {
  const router = useRouter();
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function open(event: FormEvent) {
    event.preventDefault();
    if (opening) return;
    setOpening(true);
    openLink(token).then(
      (opened) => router.replace(`/sign/${opened.recipient_id}`),
      (failure: unknown) => setError(failure),
    );
  }

  if (error) return <SignerProblem error={error} />;
  return (
    <AuthPanel eyebrow="Signing" heading="You have a document to review" onSubmit={open}>
      <Button type="submit" disabled={opening}>
        {opening ? "Opening…" : "Review document"}
      </Button>
    </AuthPanel>
  );
}
