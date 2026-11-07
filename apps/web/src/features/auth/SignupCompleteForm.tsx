"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { fieldErrors, formError } from "@/shared/api/errors";
import { usePasswordRules } from "@/shared/api/usePasswordRules";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import { useLogIn } from "@/shared/session";
import { AuthPanel, Button, Notice, PasswordField, TextField } from "@/shared/ui";

import { LinkProblem } from "./LinkProblem";
import { useLinkCheck } from "./useLinkCheck";

type Input = { token: string; workspace_name: string; name: string; password: string };

const verify = (token: string) =>
  unwrap(api.POST("/api/v1/auth/signup/verify", { body: { token } }));

/** Opened from the emailed link: the prototype's sign-up fields, then straight into the console. */
export function SignupCompleteForm() {
  const router = useRouter();
  const rules = usePasswordRules();
  const { token, check } = useLinkCheck("signup", verify);
  const [workspaceName, setWorkspaceName] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const logIn = useLogIn();
  const complete = useIdempotentAction<Input, { email: string }>(
    "signup-complete",
    (input, key) =>
      unwrap(
        api.POST("/api/v1/auth/signup/complete", {
          body: input,
          headers: { "Idempotency-Key": key },
        }),
      ),
    { persistInput: false }, // holds the password
  );

  const email = check.data?.email ?? null;
  const created = complete.state.status === "success";
  // Created: log in with the password still in memory (the completion sets no session).
  useEffect(() => {
    if (created && email && logIn.isIdle) {
      logIn.mutate({ email, password }, { onSuccess: () => router.replace("/") });
    }
  }, [created, email, logIn, password, router]);

  if (token === null) return <LinkProblem eyebrow="New workspace" missing again={{ href: "/signup", label: "Start again" }} />;
  if (check.isError) return <LinkProblem eyebrow="New workspace" error={check.error} again={{ href: "/signup", label: "Start again" }} />;
  if (!check.data) return <AuthPanel eyebrow="New workspace" heading="Checking your link…">{null}</AuthPanel>;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token) return;
    complete.run({ token, workspace_name: workspaceName, name, password });
  };
  const errors = fieldErrors(complete.state.error);
  const problem = complete.state.status === "retrying" ? "Connection lost — retrying…" : formError(complete.state.error ?? logIn.error);
  const busy = complete.isPending || created;
  return (
    <AuthPanel eyebrow="New workspace" heading="Begin." onSubmit={submit}>
      {problem ? <Notice tone="warning">{problem}</Notice> : null}
      <TextField label="Work email" value={check.data.email} readOnly autoComplete="username" />
      <TextField
        label="Firm name"
        name="organization"
        autoComplete="organization"
        required
        maxLength={120}
        value={workspaceName}
        error={errors.workspace_name}
        onChange={(event) => setWorkspaceName(event.target.value)}
      />
      <TextField
        label="Your name"
        name="name"
        autoComplete="name"
        required
        maxLength={120}
        value={name}
        error={errors.name}
        onChange={(event) => setName(event.target.value)}
      />
      <PasswordField
        label="Password"
        name="password"
        autoComplete="new-password"
        required
        {...(rules.minLength ? { minLength: rules.minLength } : {})}
        hint={rules.hint}
        value={password}
        error={errors.password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <Button type="submit" arrow loading={busy} loadingLabel="Creating…">
        Create workspace
      </Button>
    </AuthPanel>
  );
}
