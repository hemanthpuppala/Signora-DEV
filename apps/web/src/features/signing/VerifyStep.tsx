"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import { AuthPanel, BodyText, CodeField, Notice, SmallText, TextButton } from "@/shared/ui";

import { sendCode, signerKey, verifyCode, type SignerState } from "./api";

/** Seconds left until `until` (a clock time in ms), counting down once a second. */
function useCountdown(until: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (until === null) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [until]);
  return until === null ? 0 : Math.max(0, Math.ceil((until - now) / 1000));
}

function codeProblem(error: unknown): string | undefined {
  if (error instanceof ApiError && error.code === "code-ended") {
    return "That code has ended. Send a new code.";
  }
  return fieldErrors(error).code;
}

/** Step 1 of the signer's flow (Phase 8 §2): the email code, sent as the step opens. */
export function VerifyStep({ state }: { state: SignerState }) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [resendAt, setResendAt] = useState<number | null>(null);
  const send = useMutation({
    mutationFn: (again: boolean) => sendCode(state.recipient_id, again),
    onSuccess: (sent) => setResendAt(Date.now() + sent.resend_after * 1000),
  });
  const verify = useMutation({
    mutationFn: (value: string) => verifyCode(state.recipient_id, value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: signerKey(state.recipient_id) }),
    onError: () => setCode(""),
  });
  const wait = useCountdown(resendAt);

  // The code is sent when the person reaches this step; a live one is kept, never re-sent.
  const { mutate: sendFirst } = send;
  useEffect(() => sendFirst(false), [sendFirst]);

  const sentTo = send.data?.email_masked ?? state.email_masked;
  return (
    <AuthPanel eyebrow="Step 1 · verify it's you" heading="Enter your code.">
      <BodyText>
        We sent a 6-digit code to {sentTo}. It works for 10 minutes.
      </BodyText>
      {send.isError ? <Notice tone="warning">{formError(send.error)}</Notice> : null}
      <CodeField
        label="Code"
        value={code}
        onChange={setCode}
        onComplete={(value) => verify.mutate(value)}
        error={verify.isError ? codeProblem(verify.error) : undefined}
        disabled={verify.isPending}
        autoFocus
      />
      <SmallText>
        <TextButton
          onClick={() => {
            verify.reset();
            send.mutate(true);
          }}
          disabled={wait > 0 || send.isPending}
        >
          {wait > 0 ? `Send a new code in ${wait} s` : "Send a new code"}
        </TextButton>
      </SmallText>
    </AuthPanel>
  );
}
