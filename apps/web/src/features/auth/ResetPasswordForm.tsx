"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { fieldErrors, formError } from "@/shared/api/errors";
import { usePasswordRules } from "@/shared/api/usePasswordRules";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import { AuthPanel, BodyText, Button, Notice, PasswordField, TextField } from "@/shared/ui";

import { LinkProblem } from "./LinkProblem";
import { useLinkCheck } from "./useLinkCheck";

type Input = { token: string; password: string };
const AGAIN = { href: "/forgot-password", label: "Send a new link" };

const verify = (token: string) =>
  unwrap(api.POST("/api/v1/auth/password/reset/verify", { body: { token } }));

export function ResetPasswordForm() {
  const router = useRouter();
  const rules = usePasswordRules();
  const { token, check } = useLinkCheck("reset", verify);
  const [password, setPassword] = useState("");
  const reset = useIdempotentAction<Input, { email: string }>(
    "password-reset",
    (input, key) =>
      unwrap(
        api.POST("/api/v1/auth/password/reset", {
          body: input,
          headers: { "Idempotency-Key": key },
        }),
      ),
    { persistInput: false }, // holds the password
  );

  const done = reset.state.status === "success" ? reset.state.data?.email : null;
  // Signed out everywhere by the reset: log in again with the new password (OWASP).
  useEffect(() => {
    if (done) router.replace(`/login?reset=1&email=${encodeURIComponent(done)}`);
  }, [done, router]);

  if (token === null) return <LinkProblem eyebrow="Password" missing again={AGAIN} />;
  if (check.isError) return <LinkProblem eyebrow="Password" error={check.error} again={AGAIN} />;
  if (!check.data) return <AuthPanel eyebrow="Password" heading="Checking your link…">{null}</AuthPanel>;
  if (reset.state.error?.code === "link-expired") return <LinkProblem eyebrow="Password" error={reset.state.error} again={AGAIN} />;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (token) reset.run({ token, password });
  };
  const problem = reset.state.status === "retrying" ? "Connection lost — retrying…" : formError(reset.state.error);
  return (
    <AuthPanel eyebrow="Password" heading="Choose a new one." onSubmit={submit}>
      {problem ? <Notice tone="warning">{problem}</Notice> : null}
      <BodyText>Choosing a new password signs you out on every device.</BodyText>
      <TextField label="Email" value={check.data.email} readOnly autoComplete="username" />
      <PasswordField
        label="New password"
        name="password"
        autoComplete="new-password"
        required
        {...(rules.minLength ? { minLength: rules.minLength } : {})}
        {...(rules.hint ? { hint: rules.hint } : {})}
        value={password}
        error={fieldErrors(reset.state.error).password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <Button type="submit" arrow loading={reset.isPending || Boolean(done)} loadingLabel="Saving…">
        Set password
      </Button>
    </AuthPanel>
  );
}
