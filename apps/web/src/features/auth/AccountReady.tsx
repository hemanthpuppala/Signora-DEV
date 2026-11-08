import Link from "next/link";

import { AuthPanel, BodyText } from "@/shared/ui";

/** The account exists but the automatic log-in after it failed: say so and offer log-in. */
export function AccountReady({ eyebrow, email }: { eyebrow: string; email: string }) {
  return (
    <AuthPanel eyebrow={eyebrow} heading="Your account is ready.">
      <BodyText>We couldn&rsquo;t sign you in automatically.</BodyText>
      <Link href={`/login?email=${encodeURIComponent(email)}`}>Log in to continue</Link>
    </AuthPanel>
  );
}
