"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import {
  ActionBar,
  Button,
  Dialog,
  HeadRow,
  Heading1,
  IconButton,
  Notice,
  PdfViewer,
  Section,
  SmallText,
  StatusPill,
  TextButton,
  TextField,
  useToast,
  type PdfOverlayArgs,
} from "@/shared/ui";

import {
  ENVELOPE_STATUS,
  envelopeKey,
  envelopesKey,
  RECIPIENT_STATUS,
  useEnvelope,
  useSendForm,
  type Envelope,
  type Recipient,
} from "./api";
import { day } from "./EnvelopesList";
import styles from "./envelopes.module.css";
import { ValuesOverlay } from "./ValuesOverlay";

const OPEN = new Set<Envelope["status"]>(["sent", "opened", "viewed", "signed"]);
const LIVE = new Set<Recipient["status"]>(["sent", "opened", "viewed"]);

/** What happened, in words, for the timeline (the audit entries' actions). */
function happened(entry: Envelope["timeline"][number], envelope: Envelope): string {
  const who = (id: unknown) => envelope.recipients.find((r) => r.id === id)?.name ?? "someone";
  const data = entry.data as Record<string, unknown>;
  switch (entry.action) {
    case "envelope.sent":
      return `Sent to ${String(data.signers)} ${data.signers === 1 ? "signer" : "signers"}`;
    case "envelope.reminded":
      return `Reminded ${String(data.recipients)} ${data.recipients === 1 ? "person" : "people"}`;
    case "envelope.resent":
      return `Emailed ${who(data.recipient_id)} again`;
    case "envelope.recipient_changed":
      return data.email_changed ? `Changed ${who(data.recipient_id)}'s email; a new link was sent` : `Renamed ${who(data.recipient_id)}`;
    case "envelope.link_copied":
      return `Copied ${who(data.recipient_id)}'s signing link`;
    case "envelope.cancelled":
      return "Withdrawn";
    default:
      return entry.action;
  }
}

function role(recipient: Recipient): string {
  if (recipient.kind === "copy") return "Receives a copy";
  return `${recipient.kind === "signer" ? "Signer" : "Countersigner"} · ${recipient.party_label ?? ""}`;
}

/** When the person last moved: "Signed Nov 9", "Sent Nov 9", "Waiting". */
function when(recipient: Recipient): string {
  const at = recipient.signed_at ?? recipient.viewed_at ?? recipient.opened_at ?? recipient.sent_at;
  const label = RECIPIENT_STATUS[recipient.status];
  return at && recipient.status !== "waiting" ? `${label} ${day(at)}` : label;
}

/**
 * One envelope (Phase 7 §6; the prototype's screen 16): where it stands and what can be done (Remind
 * now, Cancel envelope), each recipient with Copy signing link, Send again and a correction of their
 * email, an email that was not delivered with its reason, the document as sent with its values, and
 * what happened.
 */
export function EnvelopePage({ departmentId, envelopeId }: { departmentId: string; envelopeId: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const envelope = useEnvelope(envelopeId);
  const data = envelope.data;
  const form = useSendForm(data?.document_id ?? null, data?.version_id ?? null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);

  const refresh = (updated?: Envelope) => {
    if (updated) queryClient.setQueryData(envelopeKey(envelopeId), updated);
    else void queryClient.invalidateQueries({ queryKey: envelopeKey(envelopeId) });
    void queryClient.invalidateQueries({ queryKey: envelopesKey(departmentId) });
    void queryClient.invalidateQueries({ queryKey: ["department", departmentId] });
  };
  const path = { envelope_id: envelopeId };
  const remind = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/envelopes/{envelope_id}/remind", { params: { path }, headers: { "Idempotency-Key": crypto.randomUUID() } })),
    onSuccess: (answer) => {
      toast.show(answer.reminded === 1 ? "Reminded 1 person" : `Reminded ${answer.reminded} people`);
      refresh();
    },
  });
  const resend = useMutation({
    mutationFn: (recipientId: string) =>
      unwrap(
        api.POST("/api/v1/envelopes/{envelope_id}/recipients/{recipient_id}/resend", {
          params: { path: { ...path, recipient_id: recipientId } },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        }),
      ),
    onSuccess: () => {
      toast.show("Sent again");
      refresh();
    },
  });
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/envelopes/{envelope_id}/cancel", { params: { path } })),
    onSuccess: (updated) => {
      setConfirmCancel(false);
      refresh(updated);
    },
  });
  const copy = async (recipient: Recipient) => {
    try {
      const link = await unwrap(
        api.GET("/api/v1/envelopes/{envelope_id}/recipients/{recipient_id}/link", {
          params: { path: { ...path, recipient_id: recipient.id } },
        }),
      );
      await navigator.clipboard.writeText(link.url);
      toast.show(`${recipient.name}'s link copied`);
      refresh();
    } catch (error) {
      toast.show(error instanceof ApiError ? formError(error) ?? "Couldn't copy the link" : "Couldn't copy the link");
    }
  };

  if (envelope.isError) {
    const missing = envelope.error instanceof ApiError && envelope.error.status === 404;
    return <Notice tone="warning">{missing ? "This envelope doesn't exist." : formError(envelope.error)}</Notice>;
  }
  if (!data) return null;
  const open = OPEN.has(data.status);
  const status = ENVELOPE_STATUS[data.status];
  const waiting = data.recipients.filter((r) => LIVE.has(r.status)).length;
  const failed = data.recipients.filter((r) => r.delivery?.status === "failed");

  return (
    <>
      <HeadRow back={{ href: `/departments/${departmentId}`, label: "Envelopes" }}>
        <Heading1>{data.title}</Heading1>
        <SmallText>{`${data.document_name} · version ${data.version_number} · sent by ${data.sent_by.name}`}</SmallText>
      </HeadRow>
      <ActionBar
        label="Envelope"
        actions={
          open ? (
            <>
              {waiting > 0 ? (
                <Button variant="quiet" compact loading={remind.isPending} loadingLabel="Reminding…" onClick={() => remind.mutate()}>
                  Remind now
                </Button>
              ) : null}
              <Button variant="destructive" compact onClick={() => setConfirmCancel(true)}>
                Cancel envelope
              </Button>
            </>
          ) : null
        }
      >
        <StatusPill status={status.pill} label={status.label} />
        <span>{`Sent ${day(data.sent_at)}`}</span>
        <span>{data.cancelled_at ? `Withdrawn ${day(data.cancelled_at)}` : `Expires ${day(data.expires_at)}`}</span>
        <span>{data.require_email_code ? "Email code on" : "Email code off"}</span>
      </ActionBar>
      {remind.error ? <Notice tone="warning">{formError(remind.error)}</Notice> : null}
      {failed.length > 0 ? (
        <Notice tone="warning" title={failed.length === 1 ? "An email was not delivered" : "Emails were not delivered"}>
          {failed.map((r) => `${r.name} (${r.email}): ${r.delivery?.error ?? "not delivered"}`).join(" · ")}
        </Notice>
      ) : null}

      <div className={styles.envelope}>
        <Section title="Recipients">
          <ul className={styles.recipients} aria-label="Recipients">
            {data.recipients.map((recipient) => (
              <li key={recipient.id} className={styles.recipient}>
                {editing === recipient.id ? (
                  <ChangeRecipient
                    envelopeId={envelopeId}
                    recipient={recipient}
                    onDone={(updated) => {
                      setEditing(null);
                      if (updated) refresh(updated);
                    }}
                  />
                ) : (
                  <>
                    <div className={styles.who}>
                      <span className={styles.name}>{recipient.name}</span>
                      <span className={styles.sub}>{`${recipient.email} · ${role(recipient)}`}</span>
                      {recipient.delivery?.status === "failed" ? (
                        <span className={styles.error}>{`Email not delivered: ${recipient.delivery.error ?? "unknown reason"}`}</span>
                      ) : null}
                    </div>
                    <span className={styles.state}>{when(recipient)}</span>
                    {open && LIVE.has(recipient.status) ? (
                      <span className={styles.rowActions}>
                        <TextButton onClick={() => void copy(recipient)}>Copy link</TextButton>
                        <TextButton disabled={resend.isPending} onClick={() => resend.mutate(recipient.id)}>
                          Send again
                        </TextButton>
                        {recipient.kind !== "countersigner" ? (
                          <IconButton icon="edit" label={`Change ${recipient.name}'s email`} onClick={() => setEditing(recipient.id)} />
                        ) : null}
                      </span>
                    ) : null}
                  </>
                )}
              </li>
            ))}
          </ul>
          {resend.error ? <Notice tone="warning">{formError(resend.error)}</Notice> : null}
        </Section>

        <Section title="Document">
          {form.data ? (
            <div className={styles.preview}>
              <PdfViewer
                url={`/api/v1/documents/${data.document_id}/versions/${data.version_id}/pdf`}
                pages={form.data.pages.map((p) => ({ width: p.width, height: p.height, rotation: 0 }))}
                label={`${data.document_name} as sent`}
                renderOverlay={({ page, scale }: PdfOverlayArgs) => {
                  const fields = new Map(form.data.fields.map((f) => [f.id, f]));
                  return (
                    <ValuesOverlay
                      page={page}
                      scale={scale}
                      shown={[
                        ...data.values.flatMap((v) => {
                          const field = fields.get(v.field_id);
                          return field ? [{ places: field.places, holds: field.holds, value: v.value }] : [];
                        }),
                        // A party's name fields: the name its signer signs as, once they sign.
                        ...form.data.fields.flatMap((f) => {
                          const recipient = data.recipients.find((r) => r.party_id === f.party_id);
                          const given = data.values.some((v) => v.field_id === f.id);
                          return f.from_recipient === "name" && recipient && !given
                            ? [{ places: f.places, holds: f.holds, value: recipient.name, atSigning: true }]
                            : [];
                        }),
                      ]}
                    />
                  );
                }}
              />
            </div>
          ) : (
            <SmallText>{`${data.values.length} ${data.values.length === 1 ? "value" : "values"} filled in before sending.`}</SmallText>
          )}
        </Section>

        <Section title="Timeline">
          <ol className={styles.timeline} aria-label="Timeline">
            {data.timeline.map((entry, index) => (
              <li key={index}>
                <span className={styles.sub}>{new Date(entry.at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
                <span>{happened(entry, data)}</span>
                {entry.by ? <span className={styles.sub}>{entry.by}</span> : null}
              </li>
            ))}
          </ol>
        </Section>
      </div>

      {confirmCancel ? (
        <Dialog
          title="Cancel this envelope?"
          onClose={() => setConfirmCancel(false)}
          actions={
            <>
              <Button variant="destructive" loading={cancel.isPending} loadingLabel="Cancelling…" onClick={() => cancel.mutate()}>
                Cancel envelope
              </Button>
              <TextButton onClick={() => setConfirmCancel(false)}>Keep it</TextButton>
            </>
          }
        >
          Every signing link stops working, and the signers who haven&apos;t signed are told it was withdrawn.
          {cancel.error ? <Notice tone="warning">{formError(cancel.error)}</Notice> : null}
        </Dialog>
      ) : null}
    </>
  );
}

/** Correct a person's email (their old link stops working; a new one is emailed) or, before they open it, their name. */
function ChangeRecipient({
  envelopeId,
  recipient,
  onDone,
}: {
  envelopeId: string;
  recipient: Recipient;
  onDone: (updated: Envelope | null) => void;
}) {
  const [email, setEmail] = useState(recipient.email);
  const [name, setName] = useState(recipient.name);
  const change = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/v1/envelopes/{envelope_id}/recipients/{recipient_id}", {
          params: { path: { envelope_id: envelopeId, recipient_id: recipient.id } },
          body: {
            ...(email.trim() !== recipient.email ? { email: email.trim() } : {}),
            ...(name.trim() !== recipient.name ? { name: name.trim() } : {}),
          },
        }),
      ),
    onSuccess: (updated) => onDone(updated),
  });
  const errors = fieldErrors(change.error);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    change.mutate();
  };
  return (
    <form className={styles.change} onSubmit={submit} aria-label={`Change ${recipient.name}`}>
      <div className={styles.pair}>
        <TextField label="Name" maxLength={120} value={name} error={errors.name} onChange={(event) => setName(event.target.value)} />
        <TextField label="Email" type="email" maxLength={254} value={email} error={errors.email} onChange={(event) => setEmail(event.target.value)} />
      </div>
      <SmallText>A new email changes their link: the one they were sent stops working.</SmallText>
      {change.error && !Object.keys(errors).length ? <Notice tone="warning">{formError(change.error)}</Notice> : null}
      <div className={styles.inline}>
        <Button type="submit" variant="quiet" compact loading={change.isPending} loadingLabel="Saving…">
          Save
        </Button>
        <TextButton onClick={() => onDone(null)}>Cancel</TextButton>
      </div>
    </form>
  );
}
