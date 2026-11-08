"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { fieldErrors, formError } from "@/shared/api/errors";
import { usePasswordRules } from "@/shared/api/usePasswordRules";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import { fetchSession, useLogIn, useSignOut } from "@/shared/session";
import {
  AuthPanel,
  BodyText,
  Button,
  Notice,
  PasswordField,
  SmallText,
  TextField,
} from "@/shared/ui";

import { LinkProblem } from "./LinkProblem";
import { useLinkCheck } from "./useLinkCheck";

type Input = { token: string; name: string; password: string };
const AGAIN = { href: "/login", label: "Go to log in" };

const verify = (token: string) =>
  unwrap(api.POST("/api/v1/invites/verify", { body: { token } }));

/** Screen 04. Someone else signed in on this browser is signed out first, with a notice. */
export function AcceptInviteForm() {
  const router = useRouter();
  const rules = usePasswordRules();
  const queryClient = useQueryClient();
  const { token, check } = useLinkCheck("invite", verify);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [signedOutOther, setSignedOutOther] = useState<string | null>(null);
  const signOut = useSignOut();
  const logIn = useLogIn();
  const accept = useIdempotentAction<Input, { email: string }>(
    "invite-accept",
    (input, key) =>
      unwrap(
        api.POST("/api/v1/invites/accept", { body: input, headers: { "Idempotency-Key": key } }),
      ),
    { persistInput: false }, // holds the password
  );

  const email = check.data?.email ?? null;
  // Another account signed in here: sign it out so the invitee does not act as that person.
  useEffect(() => {
    if (!email) return;
    void queryClient.fetchQuery({ queryKey: ["me"], queryFn: fetchSession }).then((me) => {
      if (me && me.user.email !== email) {
        setSignedOutOther(me.user.email);
        signOut.mutate();
      }
    });
    // Runs once per checked invitation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email]);

  const accepted = accept.state.status === "success";
  useEffect(() => {
    if (accepted && email && logIn.isIdle) {
      logIn.mutate({ email, password }, { onSuccess: () => router.replace("/") });
    }
  }, [accepted, email, logIn, password, router]);

  if (token === null) return <LinkProblem eyebrow="Invitation" missing again={AGAIN} />;
  if (check.isError) return <LinkProblem eyebrow="Invitation" error={check.error} again={AGAIN} />;
  if (!check.data) return <AuthPanel eyebrow="Invitation" heading="Checking your invitation…">{null}</AuthPanel>;

  const invite = check.data;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (token) accept.run({ token, name, password });
  };
  const errors = fieldErrors(accept.state.error);
  const problem = accept.state.status === "retrying" ? "Connection lost — retrying…" : formError(accept.state.error ?? logIn.error);
  return (
    <AuthPanel eyebrow={`Invitation · ${invite.workspace_name}`} heading="Join your team." onSubmit={submit}>
      {signedOutOther ? (
        <Notice title="Signed out">
          {signedOutOther} was signed in on this browser and has been signed out.
        </Notice>
      ) : null}
      {problem ? <Notice tone="warning">{problem}</Notice> : null}
      <BodyText>
        {invite.inviter_name} invited you to join {invite.workspace_name}. Your role:{" "}
        <b>{invite.role_name}</b>.
      </BodyText>
      {invite.role_description ? <SmallText>{invite.role_description}</SmallText> : null}
      <TextField label="Email" value={invite.email} readOnly autoComplete="username" />
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
        label="Set a password"
        name="password"
        autoComplete="new-password"
        required
        {...(rules.minLength ? { minLength: rules.minLength } : {})}
        {...(rules.hint ? { hint: rules.hint } : {})}
        value={password}
        error={errors.password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <Button type="submit" arrow loading={accept.isPending || accepted} loadingLabel="Joining…">
        Accept invitation
      </Button>
    </AuthPanel>
  );
}
