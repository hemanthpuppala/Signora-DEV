import { ApiError, formError } from "@/shared/api/errors";
import { AuthPanel, BodyText, Notice } from "@/shared/ui";

const EYEBROW = "Signing";

/** Every link that cannot be used reads the same: it never says why (Phase 8 §1.1.6). */
export function LinkClosed() {
  return (
    <AuthPanel eyebrow={EYEBROW} heading="This request is no longer open.">
      <BodyText>Nothing more is needed from you.</BodyText>
    </AuthPanel>
  );
}

/** The session ended, or this browser never opened the link (Phase 8 §1.3). */
export function SessionEnded() {
  return (
    <AuthPanel eyebrow={EYEBROW} heading="Your session ended.">
      <BodyText>Open the link in your email again to continue. Nothing you saved is lost.</BodyText>
      <BodyText>If this keeps happening, allow cookies for this site.</BodyText>
    </AuthPanel>
  );
}

/** The screen for an answer from the signer's API that is not a success. */
export function SignerProblem({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.code === "link-closed") return <LinkClosed />;
  if (error instanceof ApiError && error.code === "session-ended") return <SessionEnded />;
  return (
    <AuthPanel eyebrow={EYEBROW} heading="Something went wrong.">
      <Notice tone="warning">{formError(error)}</Notice>
    </AuthPanel>
  );
}
