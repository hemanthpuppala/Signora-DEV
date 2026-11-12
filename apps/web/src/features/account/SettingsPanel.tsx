"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { fieldErrors, formError } from "@/shared/api/errors";
import { usePasswordRules } from "@/shared/api/usePasswordRules";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import { can, SESSION_QUERY_KEY, type Me } from "@/shared/session";
import {
  Button,
  FieldAction,
  FieldGrid,
  Notice,
  PasswordField,
  Section,
  TextField,
  useToast,
} from "@/shared/ui";

/** Your name and password; the company's name for those allowed to rename it, and its website
 * for its owner. */
export function SettingsPanel({ me }: { me: Me }) {
  return (
    <>
      <ProfileForm me={me} />
      <PasswordForm />
      {can(me, "workspace.rename") ? <WorkspaceForm me={me} /> : null}
    </>
  );
}

function ProfileForm({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(me.user.name);
  const save = useMutation({
    mutationFn: (value: string) => unwrap(api.PATCH("/api/v1/me", { body: { name: value } })),
    onSuccess: (updated) => {
      queryClient.setQueryData(SESSION_QUERY_KEY, updated);
      toast.show("Name saved");
    },
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    save.mutate(name);
  };
  return (
    <form onSubmit={submit} noValidate>
      <Section title="Your profile">
        {formError(save.error) ? <Notice tone="warning">{formError(save.error)}</Notice> : null}
        <FieldGrid>
          <TextField label="Email" value={me.user.email} readOnly />
          <TextField
            label="Your name"
            autoComplete="name"
            required
            maxLength={120}
            value={name}
            error={fieldErrors(save.error).name}
            onChange={(event) => setName(event.target.value)}
          />
          <FieldAction>
            <Button type="submit" variant="quiet" loading={save.isPending} loadingLabel="Saving…">
              Save name
            </Button>
          </FieldAction>
        </FieldGrid>
      </Section>
    </form>
  );
}

type PasswordInput = { current_password: string; new_password: string };

function PasswordForm() {
  const toast = useToast();
  const rules = usePasswordRules();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const change = useIdempotentAction<PasswordInput, unknown>(
    "password-change",
    (input, key) =>
      unwrap(api.POST("/api/v1/me/password", { body: input, headers: { "Idempotency-Key": key } })),
    { persistInput: false }, // holds passwords
  );
  const done = change.state.status === "success";
  const { reset } = change;
  useEffect(() => {
    if (!done) return;
    // Clear the fields once the change succeeded.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCurrent("");
    setNext("");
    reset();
    toast.show("Password changed; your other devices were signed out");
  }, [done, reset, toast]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    change.run({ current_password: current, new_password: next });
  };
  const errors = fieldErrors(change.state.error);
  const problem = change.state.status === "retrying" ? "Connection lost — retrying…" : formError(change.state.error);
  return (
    <form onSubmit={submit} noValidate>
      <Section title="Password">
        {problem ? <Notice tone="warning">{problem}</Notice> : null}
        <FieldGrid>
          <PasswordField
            label="Current password"
            // Typed by the person, never filled in: changing a password asks them to prove they know
            // the one they have. Browsers' own managers may ignore "off" on a password; the main
            // password managers' own opt-outs follow it (1Password, LastPass, Bitwarden, Dashlane).
            autoComplete="off"
            data-1p-ignore=""
            data-lpignore="true"
            data-bwignore=""
            data-form-type="other"
            required
            value={current}
            error={errors.current_password}
            onChange={(event) => setCurrent(event.target.value)}
          />
          <PasswordField
            label="New password"
            autoComplete="new-password"
            required
            {...(rules.minLength ? { minLength: rules.minLength } : {})}
            {...(rules.hint ? { hint: rules.hint } : {})}
            value={next}
            error={errors.new_password}
            onChange={(event) => setNext(event.target.value)}
          />
          <FieldAction>
            <Button type="submit" variant="quiet" loading={change.isPending} loadingLabel="Saving…">
              Change password
            </Button>
          </FieldAction>
        </FieldGrid>
      </Section>
    </form>
  );
}

function WorkspaceForm({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(me.workspace.name);
  const save = useMutation({
    mutationFn: (value: string) =>
      unwrap(api.PATCH("/api/v1/workspace", { body: { name: value } })),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: SESSION_QUERY_KEY });
      toast.show("Company renamed");
    },
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    save.mutate(name);
  };
  return (
    <Section title="Company">
      <form onSubmit={submit} noValidate>
        {formError(save.error) ? <Notice tone="warning">{formError(save.error)}</Notice> : null}
        <FieldGrid>
          <TextField
            label="Company name"
            autoComplete="organization"
            required
            maxLength={120}
            value={name}
            error={fieldErrors(save.error).name}
            onChange={(event) => setName(event.target.value)}
          />
          <FieldAction>
            <Button type="submit" variant="quiet" loading={save.isPending} loadingLabel="Saving…">
              Rename
            </Button>
          </FieldAction>
        </FieldGrid>
      </form>
      {me.is_creator ? <WebsiteForm me={me} /> : null}
    </Section>
  );
}

/** The owner's alone: the company's logo in the header is found from its website. */
function WebsiteForm({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [website, setWebsite] = useState(me.workspace.website ?? "");
  const save = useMutation({
    mutationFn: (value: string | null) =>
      unwrap(api.PUT("/api/v1/workspace/website", { body: { website: value } })),
    onSuccess: async (saved) => {
      setWebsite(saved.website ?? "");
      await queryClient.invalidateQueries({ queryKey: SESSION_QUERY_KEY });
      toast.show(saved.website ? "Website saved" : "Website removed");
    },
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    save.mutate(website.trim() || null);
  };
  return (
    <form onSubmit={submit} noValidate>
      {formError(save.error) ? <Notice tone="warning">{formError(save.error)}</Notice> : null}
      <FieldGrid>
        <TextField
          label="Company website"
          name="url"
          type="text"
          inputMode="url"
          autoComplete="url"
          spellCheck={false}
          placeholder="yourcompany.com"
          maxLength={2048}
          value={website}
          error={fieldErrors(save.error).website}
          onChange={(event) => setWebsite(event.target.value)}
        />
        <FieldAction>
          <Button type="submit" variant="quiet" loading={save.isPending} loadingLabel="Saving…">
            Save
          </Button>
        </FieldAction>
      </FieldGrid>
    </form>
  );
}
