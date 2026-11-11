"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { formError } from "@/shared/api/errors";
import { AuthPanel, BodyText, Button, Checkbox, Notice } from "@/shared/ui";

import { giveConsent, signerKey, type SignerState } from "./api";

/** Consent to electronic records (Phase 8 §3): the disclosure, one box, Continue. */
export function ConsentStep({ state }: { state: SignerState }) {
  const queryClient = useQueryClient();
  const [agreed, setAgreed] = useState(false);
  const agree = useMutation({
    mutationFn: () => giveConsent(state.recipient_id, state.disclosure.version),
    // A changed disclosure (409) is read again: the state carries the current text.
    onSettled: () => queryClient.invalidateQueries({ queryKey: signerKey(state.recipient_id) }),
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (agreed) agree.mutate();
  };
  return (
    <AuthPanel eyebrow="Electronic records" heading="Before you read." onSubmit={submit}>
      {state.disclosure.paragraphs.map((paragraph) => (
        <BodyText key={paragraph.title}>
          <strong>{paragraph.title}.</strong> {paragraph.text}
        </BodyText>
      ))}
      <Checkbox checked={agreed} onChange={(event) => setAgreed(event.target.checked)}>
        {state.disclosure.agreement}
      </Checkbox>
      {agree.isError ? <Notice tone="warning">{formError(agree.error)}</Notice> : null}
      <Button type="submit" disabled={!agreed || agree.isPending}>
        Continue
      </Button>
    </AuthPanel>
  );
}
