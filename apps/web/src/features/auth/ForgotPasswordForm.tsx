"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { fieldErrors, formError } from "@/shared/api/errors";
import { AuthPanel, BodyText, Button, EmailField, Notice, SmallText } from "@/shared/ui";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const request = useMutation({
    mutationFn: (address: string) =>
      unwrap(api.POST("/api/v1/auth/password/forgot", { body: { email: address } })),
  });

  if (request.isSuccess) {
    return (
      <AuthPanel eyebrow="Password" heading="Check your email.">
        <BodyText>
          If an account exists for <b>{email}</b>, you&rsquo;ll receive an email with a link to
          choose a new password. The link expires in 30 minutes.
        </BodyText>
        <SmallText>
          <Link href="/login">Back to log in</Link>
        </SmallText>
      </AuthPanel>
    );
  }
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    request.mutate(email);
  };
  const problem = formError(request.error);
  return (
    <AuthPanel eyebrow="Password" heading="Forgot it?" onSubmit={submit}>
      {problem ? <Notice tone="warning">{problem}</Notice> : null}
      <EmailField
        label="Email"
        name="email"
        autoComplete="email"
        required
        value={email}
        error={fieldErrors(request.error).email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Button type="submit" arrow loading={request.isPending}>
        Send reset link
      </Button>
      <SmallText>
        <Link href="/login">Back to log in</Link>
      </SmallText>
    </AuthPanel>
  );
}
