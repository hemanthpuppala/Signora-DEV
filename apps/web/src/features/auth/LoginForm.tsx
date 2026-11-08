"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { formError } from "@/shared/api/errors";
import { safeNext, useLogIn } from "@/shared/session";
import { AuthPanel, Button, EmailField, Notice, PasswordField, SmallText } from "@/shared/ui";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [password, setPassword] = useState("");
  const logIn = useLogIn();

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    logIn.mutate(
      { email, password },
      { onSuccess: () => router.replace(safeNext(params.get("next"))) },
    );
  };

  const problem = formError(logIn.error);
  return (
    <AuthPanel eyebrow="Client login" heading="Welcome back." onSubmit={submit}>
      {params.get("reset") ? (
        <Notice title="Password changed">Log in with your new password.</Notice>
      ) : null}
      {problem ? <Notice tone="warning">{problem}</Notice> : null}
      <EmailField
        label="Email"
        name="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <PasswordField
        label="Password"
        name="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <Button type="submit" arrow loading={logIn.isPending} loadingLabel="Logging in…">
        Log in
      </Button>
      <SmallText>
        <Link href="/forgot-password">Forgot your password?</Link>
      </SmallText>
      <SmallText>
        No account yet? <Link href="/signup">Create one</Link>
      </SmallText>
    </AuthPanel>
  );
}
