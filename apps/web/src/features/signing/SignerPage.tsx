"use client";

import { AuthPanel, BodyText } from "@/shared/ui";

import { useSigner, type SignerState } from "./api";
import { SignerProblem } from "./SignerNotices";

const HEADINGS: Record<SignerState["next"], string> = {
  verify: "Confirm it's you.",
  consent: "Before you read.",
  sign: "Review and sign.",
  done: "Signed.",
};

/** `/sign/{recipient}`: the signer's flow, one step at a time (Phase 8 §1–§9). */
export function SignerPage({ recipientId }: { recipientId: string }) {
  const signer = useSigner(recipientId);
  if (signer.isError) return <SignerProblem error={signer.error} />;
  if (!signer.data) {
    return (
      <AuthPanel eyebrow="Signing" heading="Loading…">
        {null}
      </AuthPanel>
    );
  }
  const state = signer.data;
  return (
    <AuthPanel eyebrow={`${state.company} · ${state.title}`} heading={HEADINGS[state.next]}>
      <BodyText>
        {state.sender_name} sent you this to review and sign.
      </BodyText>
    </AuthPanel>
  );
}
