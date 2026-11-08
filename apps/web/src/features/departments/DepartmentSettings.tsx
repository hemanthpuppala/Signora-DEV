"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { INVALID_EMAIL, looksLikeEmail } from "@/shared/lib/email";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import { can, type Me } from "@/shared/session";
import { ActionCell, ActionHeader, Button, EmailField, FieldAction, FieldGrid, Heading1, HeadRow, LinkButton, Notice, RowActions, Section, Select, SmallText, TablePanel, TextArea, TextButton, TextField, useToast } from "@/shared/ui";

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
      <HeadRow actions={<LinkButton href={`/departments/${id}`} variant="quiet">Back</LinkButton>}>
        <Heading1>{data.name}</Heading1>
      </HeadRow>
      <AboutForm department={data} />
      <TimingForm department={data} />
      <NotifyForm department={data} />
      <Countersigners department={data} />
      {can(me, "members.manage") ? <EditAccess departmentId={id} /> : null}
      <ArchiveSection departmentId={id} />
    </>
  );
}

function Countersigners({ department }: { department: Department }) {
  const directory = useDirectory();
  const id = department.id;
  return (
    <PeopleList
        title="Countersigners"
        empty="No countersigner. Choose one."
        initial={department.countersigners}
        candidates={directory.data}
        ordered
        departmentId={id}
        save={(ids) =>
          unwrap(
            api.PUT("/api/v1/departments/{department_id}/countersigners", {
              params: { path: { department_id: id } },
              body: { user_ids: ids },
            }),
          )
        }
        saved="Countersigners saved"
      />
  );
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
  const [name, setName] = useState(department.name);
  const [description, setDescription] = useState(department.description);
  const save = usePatch(department.id, "Saved");
  const error = save.error;
  const nameTaken = error instanceof ApiError && error.code === "department-name-taken";
  const errors = fieldErrors(error);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    save.mutate({ name, description });
  };
  return (
    <form onSubmit={submit} noValidate>
      <Section title="About">
        {error && !nameTaken && !Object.keys(errors).length ? <Notice tone="warning">{formError(error)}</Notice> : null}
        <TextField
          label="Name"
          required
          maxLength={80}
          value={name}
          error={nameTaken ? "Another department already has this name." : errors.name}
          onChange={(event) => setName(event.target.value)}
        />
        <TextArea
          label="Description"
          maxLength={500}
          value={description}
          error={errors.description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <div>
          <Button type="submit" variant="quiet" loading={save.isPending} loadingLabel="Saving…">
            Save
          </Button>
        </div>
      </Section>
    </form>
  );
}

function TimingForm({ department }: { department: Department }) {
  const settings = department.settings;
  const [interval, setReminderInterval] = useState(String(settings.reminder_interval_hours));
  const [reminders, setReminders] = useState(String(settings.max_reminders));
  const [expiry, setExpiry] = useState(String(settings.expiry_days));
  const save = usePatch(department.id, "Timing saved");
  const errors = fieldErrors(save.error);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    save.mutate({
      settings: {
        reminder_interval_hours: Number(interval),
        max_reminders: Number(reminders),
        expiry_days: Number(expiry),
      },
    });
  };
  return (
    <form onSubmit={submit} noValidate>
      <Section title="Timing">
        <FieldGrid>
          <TextField
            label="Remind every (hours)"
            type="number"
            inputMode="numeric"
            min={1}
            max={720}
            value={interval}
            error={errors["settings.reminder_interval_hours"] ?? errors.reminder_interval_hours}
            onChange={(event) => setReminderInterval(event.target.value)}
          />
          <TextField
            label="Max reminders"
            type="number"
            inputMode="numeric"
            min={0}
            max={20}
            value={reminders}
            error={errors["settings.max_reminders"] ?? errors.max_reminders}
            onChange={(event) => setReminders(event.target.value)}
          />
          <TextField
            label="Expires after (days)"
            type="number"
            inputMode="numeric"
            min={1}
            max={365}
            value={expiry}
            error={errors["settings.expiry_days"] ?? errors.expiry_days}
            onChange={(event) => setExpiry(event.target.value)}
          />
          <FieldAction>
            <Button type="submit" variant="quiet" loading={save.isPending} loadingLabel="Saving…">
              Save timing
            </Button>
          </FieldAction>
        </FieldGrid>
      </Section>
    </form>
  );
}

const NOTIFY_MAX = 5;

/** "Also notify": each Add and Remove saves straight away (no separate Save to forget). */
function NotifyForm({ department }: { department: Department }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [emails, setEmails] = useState<string[]>(department.settings.notify_emails);
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
      queryClient.setQueryData(departmentKey(department.id), updated);
      setEmails(updated.settings.notify_emails); // as the server stored them (normalised)
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
    <Section title="Also notify">
      <SmallText>The sender is always notified. Add up to {NOTIFY_MAX} more people.</SmallText>
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
    </Section>
  );
}

function useDirectory() {
  return useQuery({
    queryKey: ["directory"],
    queryFn: () => unwrap(api.GET("/api/v1/members/directory")),
  });
}

/** An editable list of people: add from ``candidates``, remove, and (if ordered) move. */
function PeopleList({
  title,
  empty,
  initial,
  candidates,
  ordered,
  departmentId,
  save,
  saved,
}: {
  title: string;
  empty: string;
  initial: Person[];
  /** Who may be added (the server decides; e.g. edit access excludes people who edit everywhere). */
  candidates: Person[] | undefined;
  ordered: boolean;
  departmentId: string;
  save: (ids: string[]) => Promise<unknown>;
  saved: string;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [people, setPeople] = useState<Person[]>(initial);
  const [adding, setAdding] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => save(people.map((p) => p.id)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: departmentKey(departmentId) });
      toast.show(saved);
    },
  });
  const options = (candidates ?? [])
    .filter((person) => !people.some((p) => p.id === person.id))
    .map((person) => ({ value: person.id, label: `${person.name} · ${person.email}` }));
  const add = () => {
    const person = candidates?.find((p) => p.id === adding);
    if (person) setPeople((list) => [...list, person]);
    setAdding(null);
  };
  const move = (index: number, by: number) =>
    setPeople((list) => {
      const next = [...list];
      const [item] = next.splice(index, 1);
      if (item) next.splice(index + by, 0, item);
      return next;
    });

  return (
    <Section title={title}>
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
                      <TextButton disabled={index === 0} onClick={() => move(index, -1)}>
                        Up
                      </TextButton>
                    </ActionCell>
                  ) : null}
                  {ordered ? (
                    <ActionCell>
                      <TextButton disabled={index === people.length - 1} onClick={() => move(index, 1)}>
                        Down
                      </TextButton>
                    </ActionCell>
                  ) : null}
                  <ActionCell>
                    <TextButton onClick={() => setPeople((list) => list.filter((p) => p.id !== person.id))}>
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
          <Button variant="quiet" disabled={!adding} onClick={add}>
            Add
          </Button>
        </FieldAction>
        <FieldAction>
          <Button loading={mutation.isPending} loadingLabel="Saving…" onClick={() => mutation.mutate()}>
            Save {title.toLowerCase()}
          </Button>
        </FieldAction>
      </FieldGrid>
      {mutation.error ? <Notice tone="warning">{formError(mutation.error)}</Notice> : null}
    </Section>
  );
}

function EditAccess({ departmentId }: { departmentId: string }) {
  const grants = useQuery({
    queryKey: ["grants", departmentId],
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
      initial={grants.data.map((grant) => ({ id: grant.user.id, name: grant.user.name, email: grant.email }))}
      candidates={candidates.data}
      ordered={false}
      departmentId={departmentId}
      save={(ids) =>
        unwrap(
          api.PUT("/api/v1/departments/{department_id}/grants", {
            params: { path: { department_id: departmentId } },
            body: { user_ids: ids },
          }),
        )
      }
      saved="Edit access saved"
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
    <Section title="Archive">
      <SmallText>An archived department is read-only and hidden from the list. You can restore it.</SmallText>
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
    </Section>
  );
}
