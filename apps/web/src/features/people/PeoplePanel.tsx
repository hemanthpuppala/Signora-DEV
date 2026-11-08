"use client";

import type { components } from "@signora/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { fieldErrors, formError } from "@/shared/api/errors";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import type { Me } from "@/shared/session";
import {
  ActionCell,
  ActionHeader,
  Button,
  FieldAction,
  FieldGrid,
  Notice,
  RowActions,
  Section,
  Select,
  SmallText,
  TablePanel,
  TextButton,
  TextField,
  useToast,
} from "@/shared/ui";

type Member = components["schemas"]["MemberView"];
type Invite = components["schemas"]["InviteView"];

const MEMBERS = ["members"] as const;
const INVITES = ["invites"] as const;

const date = (value: string) =>
  new Date(value).toLocaleDateString(undefined, { month: "short", day: "2-digit" });

/** Screen 19 (People): visible with members.manage, by default only the creator. */
export function PeoplePanel({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const members = useQuery({ queryKey: MEMBERS, queryFn: () => unwrap(api.GET("/api/v1/members")) });
  const invites = useQuery({ queryKey: INVITES, queryFn: () => unwrap(api.GET("/api/v1/invites")) });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => unwrap(api.GET("/api/v1/roles")) });
  const roleOptions = (roles.data ?? []).map((role) => ({ value: role.id, label: role.name }));
  const defaultRole = roles.data?.find((role) => role.key === "read")?.id ?? null;
  const changed = useCallback(
    (message: string) => {
      toast.show(message);
      void queryClient.invalidateQueries({ queryKey: MEMBERS });
      void queryClient.invalidateQueries({ queryKey: INVITES });
    },
    [toast, queryClient],
  );
  const invited = useCallback((email: string) => changed(`Invitation sent to ${email}`), [changed]);

  return (
    <>
      <InviteForm
        roleOptions={roleOptions}
        defaultRole={defaultRole}
        onInvited={invited}
      />
      <Section title="Members">
        {members.isError ? <Notice tone="warning">{formError(members.error)}</Notice> : null}
        <TablePanel>
          <table>
            <thead>
              <tr>
                <th>Member</th>
                <th>Role</th>
                <ActionHeader label="Remove" />
              </tr>
            </thead>
            <tbody>
              {(members.data ?? []).map((member) => (
                <MemberRow key={member.id} member={member} me={me} roleOptions={roleOptions} onChanged={changed} />
              ))}
            </tbody>
          </table>
        </TablePanel>
      </Section>
      <Section title="Pending invitations">
        {invites.data && invites.data.length === 0 ? <SmallText>No pending invitations.</SmallText> : null}
        {invites.data && invites.data.length > 0 ? (
          <TablePanel>
            <table>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Invited</th>
                  <ActionHeader label="Resend" grow />
                  <ActionHeader label="Revoke" />
                </tr>
              </thead>
              <tbody>
                {invites.data.map((invite) => (
                  <InviteRow key={invite.id} invite={invite} onChanged={changed} />
                ))}
              </tbody>
            </table>
          </TablePanel>
        ) : null}
      </Section>
    </>
  );
}

function InviteForm({
  roleOptions,
  defaultRole,
  onInvited,
}: {
  roleOptions: { value: string; label: string }[];
  defaultRole: string | null;
  onInvited: (email: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState<string | null>(null);
  const chosenRole = roleId ?? defaultRole;
  const invite = useIdempotentAction<{ email: string; role_id: string }, Invite>(
    "invite-create",
    (input, key) =>
      unwrap(api.POST("/api/v1/invites", { body: input, headers: { "Idempotency-Key": key } })),
  );
  const sent = invite.state.status === "success" ? invite.state.data : null;
  const { reset } = invite;
  useEffect(() => {
    if (!sent) return;
    // Announce and clear for the next invitation once the action succeeded.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEmail("");
    reset();
    onInvited(sent.email);
  }, [sent, reset, onInvited]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (chosenRole) invite.run({ email, role_id: chosenRole });
  };
  const errors = fieldErrors(invite.state.error);
  const problem = invite.state.status === "retrying" ? "Connection lost — retrying…" : formError(invite.state.error);
  return (
    <form onSubmit={submit} noValidate>
      <Section title="Invite">
        {problem ? <Notice tone="warning">{problem}</Notice> : null}
        <FieldGrid>
          <TextField
            label="Invite by email"
            type="email"
            autoComplete="off"
            required
            value={email}
            error={errors.email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <Select label="Invite as" options={roleOptions} value={chosenRole} onChange={setRoleId} />
          <FieldAction>
            <Button type="submit" variant="quiet" loading={invite.isPending} disabled={!chosenRole}>
              Send invite
            </Button>
          </FieldAction>
        </FieldGrid>
      </Section>
    </form>
  );
}

function MemberRow({
  member,
  me,
  roleOptions,
  onChanged,
}: {
  member: Member;
  me: Me;
  roleOptions: { value: string; label: string }[];
  onChanged: (message: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const changeRole = useMutation({
    mutationFn: (roleId: string) =>
      unwrap(
        api.PATCH("/api/v1/members/{user_id}", {
          params: { path: { user_id: member.id } },
          body: { role_id: roleId },
        }),
      ),
    onSuccess: (updated) => onChanged(`${updated.name} is now ${updated.role.name}`),
  });
  const remove = useMutation({
    mutationFn: () =>
      unwrap(api.DELETE("/api/v1/members/{user_id}", { params: { path: { user_id: member.id } } })),
    onSuccess: () => onChanged(`${member.name} was removed`),
  });
  const protectedRow = member.is_creator || member.id === me.user.id;
  const problem = formError(changeRole.error ?? remove.error);
  return (
    <tr>
      <td>
        <b>{member.name}</b>
        <SmallText>{member.email}</SmallText>
        {problem ? <SmallText role="alert">{problem}</SmallText> : null}
      </td>
      <td>
        {member.is_creator ? (
          member.display_role.name
        ) : (
          <Select
            label={`Role of ${member.name}`}
            options={roleOptions}
            value={member.role.id}
            onChange={(roleId) => changeRole.mutate(roleId)}
            disabled={changeRole.isPending}
          />
        )}
      </td>
      <ActionCell>
        {protectedRow ? null : (
          <RowActions label={`Actions for ${member.name}`}>
            {confirming ? (
              <>
                <TextButton data-emphasis="true" onClick={() => remove.mutate()} disabled={remove.isPending}>
                  Confirm remove
                </TextButton>
                <TextButton onClick={() => setConfirming(false)}>Cancel</TextButton>
              </>
            ) : (
              <TextButton onClick={() => setConfirming(true)}>Remove</TextButton>
            )}
          </RowActions>
        )}
      </ActionCell>
    </tr>
  );
}

function InviteRow({ invite, onChanged }: { invite: Invite; onChanged: (message: string) => void }) {
  // One saved slot per invitation: rows must not resume or announce each other's resend.
  const resend = useIdempotentAction<string, Invite>(`invite-resend:${invite.id}`, (id, key) =>
    unwrap(
      api.POST("/api/v1/invites/{invite_id}/resend", {
        params: { path: { invite_id: id } },
        headers: { "Idempotency-Key": key },
      }),
    ),
  );
  const revoke = useMutation({
    mutationFn: () =>
      unwrap(api.DELETE("/api/v1/invites/{invite_id}", { params: { path: { invite_id: invite.id } } })),
    onSuccess: () => onChanged(`Invitation to ${invite.email} revoked`),
  });
  const resent = resend.state.status === "success";
  const { reset: resetResend } = resend;
  useEffect(() => {
    if (!resent) return;
    resetResend();
    onChanged(`Invitation resent to ${invite.email}`);
  }, [resent, resetResend, onChanged, invite.email]);
  const problem = formError(resend.state.error ?? revoke.error);
  return (
    <tr>
      <td>
        {invite.email}
        {problem ? <SmallText role="alert">{problem}</SmallText> : null}
      </td>
      <td>{invite.role.name}</td>
      <td>
        <SmallText>
          {date(invite.created_at)} · {invite.expired ? "expired" : `expires ${date(invite.expires_at)}`}
        </SmallText>
      </td>
      <ActionCell grow>
        <TextButton onClick={() => resend.run(invite.id)} disabled={resend.isPending}>
          Resend
        </TextButton>
      </ActionCell>
      <ActionCell>
        <TextButton onClick={() => revoke.mutate()} disabled={revoke.isPending}>
          Revoke
        </TextButton>
      </ActionCell>
    </tr>
  );
}
