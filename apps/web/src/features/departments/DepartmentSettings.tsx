"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { INVALID_EMAIL, looksLikeEmail } from "@/shared/lib/email";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import { can, type Me } from "@/shared/session";
import { ActionCell, ActionHeader, Block, Blocks, Button, EmailField, FieldAction, FieldGrid, Heading1, HeadRow, LinkButton, Notice, RowActions, Select, SmallText, TablePanel, TextArea, TextButton, TextField, useToast } from "@/shared/ui";

import { departmentKey, useDepartment, type Department } from "./api";

type Person = { id: string; name: string; email: string };

/** Screen 09: department settings, each section saving on its own (Phase 3 LLD §6.4). */
export function DepartmentSettings({ me, id }: { me: Me; id: string }) {
  const department = useDepartment(id);
  if (department.isError) {
    const missing = department.error instanceof ApiError && department.error.status === 404;
    return <Notice tone="warning">{missing ? "This department doesn't exist." : formError(department.error)}</Notice>;
  }
  const data = department.data;
  if (!data) return null;
  if (data.status === "archived") {
    return (
      <Notice title="Archived" action={<LinkButton href={`/departments/${id}`} variant="quiet">Open</LinkButton>}>
        Restore this department to change its settings.
      </Notice>
    );
  }
  return (
    <>
      <HeadRow back={{ href: `/departments/${id}`, label: data.name }}>
        <Heading1>Department settings</Heading1>
      </HeadRow>
      {/* One panel, a row per group: its title on the left, its fields on the right (prototype). */}
      <Blocks>
        <AboutForm department={data} />
        <TimingForm department={data} />
        <NotifyForm department={data} />
        <Countersigners department={data} />
        {can(me, "members.manage") ? <EditAccess departmentId={id} /> : null}
        <ArchiveSection departmentId={id} />
      </Blocks>
    </>
  );
}

function Countersigners({ department }: { department: Department }) {
  const queryClient = useQueryClient();
  const directory = useDirectory();
  const id = department.id;
  return (
    <PeopleList
      title="Countersigners"
      empty="No countersigner. Choose one."
      people={department.countersigners}
      candidates={directory.data}
      ordered
      save={async (ids) => {
        const saved = await unwrap(
          api.PUT("/api/v1/departments/{department_id}/countersigners", {
            params: { path: { department_id: id } },
            body: { user_ids: ids },
          }),
        );
        queryClient.setQueryData<Department>(departmentKey(id), (current) =>
          current ? { ...current, countersigners: saved } : current,
        );
      }}
      saved="Countersigners updated"
    />
  );
}

/**
 * A form field over a saved value: it shows the saved value until edited, so a refetch (another
 * manager's change) shows in untouched fields, and ``changed`` is set only when the edit differs.
 * ``reset`` drops the draft once a save has put the server's answer in the cache.
 */
function useDraft<T>(saved: T) {
  const [draft, setDraft] = useState<T | null>(null);
  const value = draft ?? saved;
  return { value, set: setDraft, changed: draft !== null && draft !== saved, reset: () => setDraft(null) };
}

function usePatch(id: string, done: string) {
  const queryClient = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.PATCH("/api/v1/departments/{department_id}", {
          params: { path: { department_id: id } },
          body,
        }),
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(departmentKey(id), updated);
      void queryClient.invalidateQueries({ queryKey: ["departments"] });
      toast.show(done);
    },
  });
}

function AboutForm({ department }: { department: Department }) {
  const name = useDraft(department.name);
  const description = useDraft(department.description);
  const save = usePatch(department.id, "Saved");
  const error = save.error;
  const nameTaken = error instanceof ApiError && error.code === "department-name-taken";
  const errors = fieldErrors(error);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // Only what this person changed, so a colleague's change to the other field is kept.
    const body = {
      ...(name.changed ? { name: name.value } : {}),
      ...(description.changed ? { description: description.value } : {}),
    };
    save.mutate(body, {
      onSuccess: () => {
        name.reset();
        description.reset();
      },
    });
  };
  return (
    <form onSubmit={submit} noValidate>
      <Block title="About">
        {error && !nameTaken && !Object.keys(errors).length ? <Notice tone="warning">{formError(error)}</Notice> : null}
        <TextField
          label="Name"
          required
          maxLength={80}
          value={name.value}
          error={nameTaken ? "Another department already has this name." : errors.name}
          onChange={(event) => name.set(event.target.value)}
        />
        <TextArea
          label="Description"
          maxLength={500}
          value={description.value}
          error={errors.description}
          onChange={(event) => description.set(event.target.value)}
        />
        <div>
          <Button type="submit" variant="quiet" loading={save.isPending} loadingLabel="Saving…">
            Save
          </Button>
        </div>
      </Block>
    </form>
  );
}

function TimingForm({ department }: { department: Department }) {
  const settings = department.settings;
  const interval = useDraft(String(settings.reminder_interval_hours));
  const reminders = useDraft(String(settings.max_reminders));
  const expiry = useDraft(String(settings.expiry_days));
  const save = usePatch(department.id, "Timing saved");
  const errors = fieldErrors(save.error);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // Only what this person changed, so a colleague's change to another field is kept.
    const changed = {
      ...(interval.changed ? { reminder_interval_hours: Number(interval.value) } : {}),
      ...(reminders.changed ? { max_reminders: Number(reminders.value) } : {}),
      ...(expiry.changed ? { expiry_days: Number(expiry.value) } : {}),
    };
    save.mutate(
      { settings: changed },
      {
        onSuccess: () => {
          interval.reset();
          reminders.reset();
          expiry.reset();
        },
      },
    );
  };
  return (
    <form onSubmit={submit} noValidate>
      <Block title="Timing">
        <FieldGrid>
          <TextField
            label="Remind every (hours)"
            type="number"
            inputMode="numeric"
            min={1}
            max={720}
            value={interval.value}
            error={errors["settings.reminder_interval_hours"] ?? errors.reminder_interval_hours}
            onChange={(event) => interval.set(event.target.value)}
          />
          <TextField
            label="Max reminders"
            type="number"
            inputMode="numeric"
            min={0}
            max={20}
            value={reminders.value}
            error={errors["settings.max_reminders"] ?? errors.max_reminders}
            onChange={(event) => reminders.set(event.target.value)}
          />
          <TextField
            label="Expires after (days)"
            type="number"
            inputMode="numeric"
            min={1}
            max={365}
            value={expiry.value}
            error={errors["settings.expiry_days"] ?? errors.expiry_days}
            onChange={(event) => expiry.set(event.target.value)}
          />
          <FieldAction>
            <Button type="submit" variant="quiet" loading={save.isPending} loadingLabel="Saving…">
              Save timing
            </Button>
          </FieldAction>
        </FieldGrid>
      </Block>
    </form>
  );
}

const NOTIFY_MAX = 5;

/** "Also notify": each Add and Remove saves straight away (no separate Save to forget). */
function NotifyForm({ department }: { department: Department }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  // The saved list, never a copy: a refetch shows a colleague's change, and Add/Remove apply to it.
  const emails = department.settings.notify_emails;
  const [draft, setDraft] = useState("");
  const [draftError, setDraftError] = useState<string | undefined>(undefined);
  const save = useMutation({
    mutationFn: (next: string[]) =>
      unwrap(
        api.PATCH("/api/v1/departments/{department_id}", {
          params: { path: { department_id: department.id } },
          body: { settings: { notify_emails: next } },
        }),
      ),
    onSuccess: (updated, next) => {
      queryClient.setQueryData(departmentKey(department.id), updated); // as stored (normalised)
      toast.show(next.length > emails.length ? "Added" : "Removed");
    },
  });
  const serverErrors = fieldErrors(save.error);
  const add = () => {
    const email = draft.trim();
    if (!looksLikeEmail(email)) {
      setDraftError(INVALID_EMAIL);
      return;
    }
    if (emails.some((existing) => existing.toLowerCase() === email.toLowerCase())) {
      setDraftError("Already in the list");
      return;
    }
    setDraftError(undefined);
    save.mutate([...emails, email], { onSuccess: () => setDraft("") });
  };
  const addError =
    draftError ??
    Object.entries(serverErrors).find(([field]) => field.startsWith("notify_emails"))?.[1] ??
    (save.error && !Object.keys(serverErrors).length ? formError(save.error) ?? undefined : undefined);
  return (
    <Block title="Also notify" hint={`The sender is always notified. Add up to ${NOTIFY_MAX} more people.`}>
      {emails.length > 0 ? (
        <TablePanel label="Also notify list">
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <ActionHeader label="Remove" />
              </tr>
            </thead>
            <tbody>
              {emails.map((email) => (
                <tr key={email}>
                  <td>{email}</td>
                  <ActionCell>
                    <TextButton
                      disabled={save.isPending}
                      onClick={() => save.mutate(emails.filter((e) => e !== email))}
                    >
                      Remove
                    </TextButton>
                  </ActionCell>
                </tr>
              ))}
            </tbody>
          </table>
        </TablePanel>
      ) : null}
      {emails.length < NOTIFY_MAX ? (
        <form
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            add();
          }}
          noValidate
        >
          <FieldGrid>
            <EmailField
              label="Email"
              autoComplete="off"
              value={draft}
              error={addError}
              onChange={(event) => {
                setDraft(event.target.value);
                setDraftError(undefined);
              }}
            />
            <FieldAction>
              <Button type="submit" variant="quiet" disabled={!draft.trim()} loading={save.isPending}>
                Add
              </Button>
            </FieldAction>
          </FieldGrid>
        </form>
      ) : null}
    </Block>
  );
}

function useDirectory() {
  return useQuery({
    queryKey: ["directory"],
    queryFn: () => unwrap(api.GET("/api/v1/members/directory")),
  });
}

/**
 * An editable list of people: add from ``candidates``, remove, and (if ordered) move. It shows
 * ``people`` as the server last returned them and keeps no copy, so a refetch (another manager's
 * change, a return to the page) shows at once and a change is never made to an old list. ``save``
 * stores the full list and writes the server's answer into the query that ``people`` comes from.
 */
function PeopleList({
  title,
  empty,
  people,
  candidates,
  ordered,
  save,
  saved,
}: {
  title: string;
  empty: string;
  people: Person[];
  /** Who may be added (the server decides; e.g. edit access excludes people who edit everywhere). */
  candidates: Person[] | undefined;
  ordered: boolean;
  save: (ids: string[]) => Promise<void>;
  saved: string;
}) {
  const toast = useToast();
  const [adding, setAdding] = useState<string | null>(null);
  // Every change saves straight away, like "Also notify".
  const mutation = useMutation({
    mutationFn: (next: Person[]) => save(next.map((p) => p.id)),
    onSuccess: () => toast.show(saved),
  });
  const commit = (next: Person[]) => mutation.mutate(next);
  const options = (candidates ?? [])
    .filter((person) => !people.some((p) => p.id === person.id))
    .map((person) => ({ value: person.id, label: `${person.name} · ${person.email}` }));
  const add = () => {
    const person = candidates?.find((p) => p.id === adding);
    if (person) commit([...people, person]);
    setAdding(null);
  };
  const move = (index: number, by: number) => {
    const next = [...people];
    const [item] = next.splice(index, 1);
    if (item) next.splice(index + by, 0, item);
    commit(next);
  };

  return (
    <Block title={title}>
      {people.length === 0 ? <SmallText>{empty}</SmallText> : null}
      {people.length > 0 ? (
        <TablePanel label={`${title} list`}>
          <table>
            <thead>
              <tr>
                <th>Person</th>
                {ordered ? <ActionHeader label="Move up" /> : null}
                {ordered ? <ActionHeader label="Move down" /> : null}
                <ActionHeader label="Remove" />
              </tr>
            </thead>
            <tbody>
              {people.map((person, index) => (
                <tr key={person.id}>
                  <td>
                    <b>{person.name}</b>
                    <SmallText>{person.email}</SmallText>
                  </td>
                  {ordered ? (
                    <ActionCell>
                      <TextButton disabled={index === 0 || mutation.isPending} onClick={() => move(index, -1)}>
                        Up
                      </TextButton>
                    </ActionCell>
                  ) : null}
                  {ordered ? (
                    <ActionCell>
                      <TextButton
                        disabled={index === people.length - 1 || mutation.isPending}
                        onClick={() => move(index, 1)}
                      >
                        Down
                      </TextButton>
                    </ActionCell>
                  ) : null}
                  <ActionCell>
                    <TextButton
                      disabled={mutation.isPending}
                      onClick={() => commit(people.filter((p) => p.id !== person.id))}
                    >
                      Remove
                    </TextButton>
                  </ActionCell>
                </tr>
              ))}
            </tbody>
          </table>
        </TablePanel>
      ) : null}
      <FieldGrid>
        <Select label="Add a person" options={options} value={adding} onChange={setAdding} />
        <FieldAction>
          <Button variant="quiet" disabled={!adding} loading={mutation.isPending} loadingLabel="Saving…" onClick={add}>
            Add
          </Button>
        </FieldAction>
      </FieldGrid>
      {mutation.error ? <Notice tone="warning">{formError(mutation.error)}</Notice> : null}
    </Block>
  );
}

function EditAccess({ departmentId }: { departmentId: string }) {
  const queryClient = useQueryClient();
  const grantsKey = ["grants", departmentId];
  const grants = useQuery({
    queryKey: grantsKey,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/departments/{department_id}/grants", {
          params: { path: { department_id: departmentId } },
        }),
      ),
  });
  const candidates = useQuery({
    queryKey: ["grant-candidates", departmentId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/departments/{department_id}/grants/candidates", {
          params: { path: { department_id: departmentId } },
        }),
      ),
  });
  if (!grants.data) return null;
  return (
    <PeopleList
      title="People with edit access"
      empty="Only owners and editors can edit here."
      people={grants.data.map((grant) => ({ id: grant.user.id, name: grant.user.name, email: grant.email }))}
      candidates={candidates.data}
      ordered={false}
      save={async (ids) => {
        const saved = await unwrap(
          api.PUT("/api/v1/departments/{department_id}/grants", {
            params: { path: { department_id: departmentId } },
            body: { user_ids: ids },
          }),
        );
        queryClient.setQueryData(grantsKey, saved);
      }}
      saved="Edit access updated"
    />
  );
}

function ArchiveSection({ departmentId }: { departmentId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const archive = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/departments/{department_id}/archive", {
          params: { path: { department_id: departmentId } },
        }),
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(departmentKey(departmentId), updated);
      void queryClient.invalidateQueries({ queryKey: ["departments"] });
      router.replace(`/departments/${departmentId}`);
    },
  });
  return (
    <Block title="Archive" hint="An archived department is read-only and hidden from the list. You can restore it.">
      <div>
        {confirming ? (
          <RowActions label="Confirm archiving">
            <Button variant="destructive" loading={archive.isPending} onClick={() => archive.mutate()}>
              Confirm archive
            </Button>
            <TextButton onClick={() => setConfirming(false)}>Cancel</TextButton>
          </RowActions>
        ) : (
          <Button variant="destructive" onClick={() => setConfirming(true)}>
            Archive department
          </Button>
        )}
      </div>
      {archive.error ? <Notice tone="warning">{formError(archive.error)}</Notice> : null}
    </Block>
  );
}
