"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { fieldErrors, formError } from "@/shared/api/errors";
import {
  AuthPanel,
  BodyText,
  Button,
  Notice,
  SmallText,
  TextButton,
  TextField,
} from "@/shared/ui";

/** Screen 02 (deviation: email only; the emailed link carries the rest). */
export function SignupStartForm() {
  const [email, setEmail] = useState("");
  const start = useMutation({
    mutationFn: (address: string) =>
      unwrap(api.POST("/api/v1/auth/signup", { body: { email: address } })),
  });

  if (start.isSuccess) {
    return (
      <AuthPanel eyebrow="New workspace" heading="Check your email.">
        <BodyText>
          We sent a link to <b>{email}</b>. Open it to name your workspace and choose a password.
          If you already have an account, the email tells you how to log in.
        </BodyText>
        <SmallText>Nothing after a few minutes? Check your spam folder.</SmallText>
        <TextButton onClick={() => start.reset()}>Use another email</TextButton>
      </AuthPanel>
    );
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    start.mutate(email);
  };
  const problem = formError(start.error);
  return (
    <AuthPanel eyebrow="New workspace" heading="Begin." onSubmit={submit}>
      {problem ? <Notice tone="warning">{problem}</Notice> : null}
      <TextField
        label="Work email"
        type="email"
        name="email"
        autoComplete="email"
        required
        value={email}
        error={fieldErrors(start.error).email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Button type="submit" arrow loading={start.isPending}>
        Continue
      </Button>
      <SmallText>
        Already have one? <Link href="/login">Log in</Link>
      </SmallText>
    </AuthPanel>
  );
}
