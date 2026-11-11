"use client";

import { useEffect, useState } from "react";

import { fieldErrors, formError } from "@/shared/api/errors";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import { AuthPanel, BodyText, Button, Dialog, Notice, TextArea, TextButton } from "@/shared/ui";

import { declineSigning } from "./api";

/**
 * Decline to sign (Phase 8 §8): final for everyone, so it asks first and asks why. Reached from the
 * signer's screen and from the consent screen (declining is how consent is withdrawn).
 */
export function DeclineDialog({
  recipientId,
  company,
  onDeclined,
  onClose,
}: {
  recipientId: string;
  company: string;
  onDeclined: () => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const decline = useIdempotentAction<string, unknown>(
    `sign-decline:${recipientId}`,
    (why, key) => declineSigning(recipientId, why, key),
    { persistInput: false },
  );
  const done = decline.state.status === "success";
  useEffect(() => {
    if (done) onDeclined();
  }, [done, onDeclined]);
  const error = decline.state.error;
  return (
    <Dialog
      title="Decline to sign"
      onClose={onClose}
      actions={
        <>
          <Button variant="destructive" disabled={!reason.trim() || decline.isPending} onClick={() => decline.run(reason.trim())}>
            Decline to sign
          </Button>
          <TextButton onClick={onClose}>Go back</TextButton>
        </>
      }
    >
      <BodyText>Declining stops this request for everyone. {company} will see your reason.</BodyText>
      <TextArea
        label="Reason"
        value={reason}
        maxLength={500}
        error={fieldErrors(error).reason}
        onChange={(event) => setReason(event.target.value)}
      />
      {error && !fieldErrors(error).reason ? <Notice tone="warning">{formError(error)}</Notice> : null}
    </Dialog>
  );
}

/** After a decline: nothing more to do. */
export function Declined({ company }: { company: string }) {
  return (
    <AuthPanel eyebrow="Declined" heading="You declined to sign.">
      <BodyText>{company} has been told your reason. Nothing more is needed from you.</BodyText>
    </AuthPanel>
  );
}
