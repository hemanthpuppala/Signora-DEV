import Link from "next/link";

import { ApiError, formError } from "@/shared/api/errors";
import { AuthPanel, BodyText, Notice, SmallText } from "@/shared/ui";

/** What a person sees when their emailed link cannot be used. */
export function LinkProblem({
  eyebrow,
  error,
  missing,
  again,
}: {
  eyebrow: string;
  error?: unknown;
  missing?: boolean;
  again: { href: string; label: string };
}) {
  const expired = missing || (error instanceof ApiError && error.code === "link-expired");
  return (
    <AuthPanel eyebrow={eyebrow} heading={expired ? "This link has expired." : "Something went wrong."}>
      {expired ? (
        <BodyText>Links work once and expire. Ask for a new one.</BodyText>
      ) : (
        <Notice tone="warning">{formError(error)}</Notice>
      )}
      <SmallText>
        <Link href={again.href}>{again.label}</Link>
      </SmallText>
    </AuthPanel>
  );
}
