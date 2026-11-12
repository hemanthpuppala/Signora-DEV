"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import {
  ActionBar,
  Button,
  DetailsPane,
  Dialog,
  FactList,
  HeadAction,
  HeadRow,
  Heading1,
  IconButton,
  LinkButton,
  Item,
  ItemAction,
  ItemActions,
  ItemHead,
  ItemList,
  MetaLine,
  Notice,
  PdfViewer,
  Section,
  SmallText,
  StatusPill,
  TextButton,
  TextField,
  type Status,
  useToast,
  ViewerLayout,
  ViewerPane,
  type PdfOverlayArgs,
} from "@/shared/ui";

import {
  ENVELOPE_STATUS,
  envelopeKey,
  envelopesKey,
  RECIPIENT_STATUS,
  useEnvelope,
  useEnvelopeDocument,
  type Envelope,
  type Recipient,
  type EnvelopeDocument,
} from "./api";
import { day } from "./EnvelopesList";
import type { SendDraft } from "./SendModal";
import styles from "./envelopes.module.css";
import { namePart } from "@/shared/document/typeset";
import { ValuesOverlay, type Shown } from "@/shared/document/ValuesOverlay";

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
      if (data.recipient_id) return `Reminded ${who(data.recipient_id)}`;
      return `Reminded ${String(data.recipients)} ${data.recipients === 1 ? "person" : "people"}${data.automatic ? " automatically" : ""}`;
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

/** The values on the document as sent: what was filled in, and each party's name to come. */
function shown(envelope: Envelope, drawn: EnvelopeDocument): Shown[] {
  const fields = new Map(drawn.fields.map((f) => [f.id, f]));
  const given = new Set(envelope.values.map((v) => v.field_id));
  return [
    ...envelope.values.flatMap((v) => {
      const field = fields.get(v.field_id);
      return field ? [{ places: field.places, holds: field.holds, value: v.value, format: field.format }] : [];
    }),
    // A party's name fields: the name its signer signs as, once they sign.
    ...drawn.fields.flatMap((f) => {
      const recipient = envelope.recipients.find((r) => r.party_id === f.party_id);
      return f.from_recipient === "name" && recipient && !given.has(f.id)
        ? [{ places: f.places, holds: f.holds, value: namePart(f.holds, recipient.name), atSigning: true }]
        : [];
    }),
  ];
}

/** A recipient's state as the design system's status pill. */
const RECIPIENT_PILL: Record<Recipient["status"], Status> = {
  waiting: "pending",
  sent: "sent",
  opened: "opened",
  viewed: "viewed",
  signed: "signed",
  declined: "declined",
};

/** "Nov 23, 2026": a date read on its own, beside its label. */
const longDay = (iso: string) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

/** The people on an envelope, by how they take part: who signs, who countersigns, who gets a copy. */
const GROUPS = [
  { kind: "signer", title: "Signers" },
  { kind: "countersigner", title: "Countersigners" },
  { kind: "copy", title: "Receives a copy" },
] as const;

/** Initials in a square, where a document card shows its page. */
function Monogram({ name }: { name: string }) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const initials = (words.length > 1 ? `${words[0]?.[0] ?? ""}${words[words.length - 1]?.[0] ?? ""}` : name.slice(0, 2)).toUpperCase();
  return (
    <span className={styles.monogram} aria-hidden="true">
      {initials}
    </span>
  );
}

/** Days left before the envelope expires: "13 days left", "Expires today". */
function left(expiresAt: string): string {
  const days = Math.ceil((new Date(expiresAt).getTime() - Date.now()) / 86_400_000);
  if (days <= 0) return "Expires today";
  return days === 1 ? "1 day left" : `${days} days left`;
}

/** The person's moments, in one quiet line: sent, read, signed; the time left to act, and when
 * they are reminded next. */
function times(recipient: Recipient, envelope: Envelope): string {
  if (recipient.kind === "copy") return "Gets the signed copy";
  if (recipient.status === "waiting") return "Emailed once every signer has signed";
  const parts = [
    recipient.sent_at ? `Sent ${day(recipient.sent_at)}` : null,
    recipient.viewed_at ? `Read ${day(recipient.viewed_at)}` : recipient.opened_at ? `Opened ${day(recipient.opened_at)}` : null,
    recipient.signed_at ? `Signed ${day(recipient.signed_at)}` : null,
    OPEN.has(envelope.status) && LIVE.has(recipient.status) ? left(envelope.expires_at) : null,
    recipient.next_reminder_at ? `Next reminder ${day(recipient.next_reminder_at)}` : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

/**
 * One envelope (Phase 7 §6; the prototype's screen 16): where it stands and what can be done (Remind
 * now, Cancel envelope), each recipient with Copy signing link, Send again and a correction of their
 * email, an email that was not delivered with its reason, the document as sent with its values, and
 * what happened.
 */
/** A send again of a declined envelope (Phase 8 §8.1.4): the same, every part correctable. */
export function draftFrom(envelope: Envelope): SendDraft {
  const declined = envelope.recipients.find((r) => r.status === "declined");
  const days = Math.max(1, Math.round((Date.parse(envelope.expires_at) - Date.parse(envelope.sent_at)) / 86_400_000));
  return {
    documentId: envelope.document_id,
    versionId: envelope.version_id,
    title: envelope.title,
    values: Object.fromEntries(envelope.values.filter((v) => v.given_by === "sender").map((v) => [v.field_id, v.value])),
    signers: Object.fromEntries(
      envelope.recipients.filter((r) => r.kind === "signer" && r.party_id).map((r) => [r.party_id as string, { name: r.name, email: r.email }]),
    ),
    countersigners: Object.fromEntries(
      envelope.recipients.filter((r) => r.kind === "countersigner" && r.party_id).map((r) => [r.party_id as string, r.email]),
    ),
    copies: envelope.recipients.filter((r) => r.kind === "copy").map((r) => ({ name: r.name, email: r.email })),
    settings: {
      require_email_code: envelope.require_email_code,
      reminder_interval_hours: envelope.reminder_interval_hours,
      max_reminders: envelope.max_reminders,
      expiry_days: days,
      notify_emails: envelope.notify_emails,
    },
    note: declined?.decline_reason ? `${declined.name} declined: “${declined.decline_reason}”` : "The earlier send ended.",
  };
}

/** A completed envelope's signed document, its certificate, or both in one file (§12.3). */
const download = (envelopeId: string, part: "document" | "certificate" | "combined") =>
  `/api/v1/envelopes/${envelopeId}/download?part=${part}`;

export function EnvelopePage({
  departmentId,
  envelopeId,
  onSendAgain,
}: {
  departmentId: string;
  envelopeId: string;
  /** Offered on a declined envelope: the route opens the send with this draft. */
  onSendAgain?: (draft: SendDraft) => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const envelope = useEnvelope(envelopeId);
  const data = envelope.data;
  const drawn = useEnvelopeDocument(envelopeId);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [shownLink, setShownLink] = useState<{ name: string; url: string } | null>(null); // the clipboard refused it

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
  const remindOne = useMutation({
    mutationFn: (recipient: Recipient) =>
      unwrap(
        api.POST("/api/v1/envelopes/{envelope_id}/recipients/{recipient_id}/remind", {
          params: { path: { ...path, recipient_id: recipient.id } },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        }),
      ),
    onSuccess: (_, recipient) => {
      toast.show(`Reminded ${recipient.name}`);
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
  /**
   * Copy a person's signing link. The link is asked for once (the server records that it was
   * given) and written to the clipboard inside the click: as a promise where the browser takes
   * one, since a browser may refuse a write that only begins after the request has answered. If
   * the clipboard cannot be written at all, the link is shown to be copied by hand: it is never
   * asked for again, and never lost.
   */
  const copy = async (recipient: Recipient) => {
    let url: string | null = null;
    const link = unwrap(
      api.GET("/api/v1/envelopes/{envelope_id}/recipients/{recipient_id}/link", {
        params: { path: { ...path, recipient_id: recipient.id } },
      }),
    ).then((answer) => (url = answer.url));
    try {
      if (typeof ClipboardItem !== "undefined" && typeof navigator.clipboard?.write === "function") {
        const text = link.then((value) => new Blob([value], { type: "text/plain" }));
        await navigator.clipboard.write([new ClipboardItem({ "text/plain": text })]);
      } else {
        await navigator.clipboard.writeText(await link);
      }
      toast.show(`${recipient.name}'s link copied`);
    } catch (error) {
      if (error instanceof ApiError) toast.show(formError(error) ?? "Couldn't get the link");
      else if (url !== null) setShownLink({ name: recipient.name, url });
      else toast.show("Couldn't get the link");
    }
    if (url !== null) refresh(); // the timeline has the link's entry
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
        <MetaLine label="Envelope">
          <StatusPill status={status.pill} label={status.label} />
          <span>{`Sent ${day(data.sent_at)} by ${data.sent_by.name}`}</span>
          <span>{data.cancelled_at ? `Withdrawn ${day(data.cancelled_at)}` : `Expires ${day(data.expires_at)}`}</span>
          <span>{`${data.document_name} · version ${data.version_number}`}</span>
        </MetaLine>
      </HeadRow>
      {remind.error ? <Notice tone="warning">{formError(remind.error)}</Notice> : null}
      {data.status === "completed" ? (
        <Notice
          title={data.completed_at ? `Completed ${day(data.completed_at)}` : "Completed"}
          action={
            <span className={styles.downloads}>
              <LinkButton href={download(data.id, "combined")} download>
                Download
              </LinkButton>
              <LinkButton href={download(data.id, "document")} variant="quiet" download>
                Document
              </LinkButton>
              <LinkButton href={download(data.id, "certificate")} variant="quiet" download>
                Certificate
              </LinkButton>
            </span>
          }
        >
          Everyone has signed. Everyone was emailed the signed document and its certificate.
        </Notice>
      ) : data.status === "signed" && data.recipients.every((r) => r.kind === "copy" || r.status === "signed") ? (
        <Notice title="Making the signed copy…">Everyone has signed. The signed document and its certificate are being made.</Notice>
      ) : null}
      {data.status === "declined"
        ? (() => {
            const who = data.recipients.find((r) => r.status === "declined");
            return (
              <Notice
                tone="warning"
                title={who ? `${who.name} declined${who.declined_at ? ` ${day(who.declined_at)}` : ""}` : "Declined"}
                action={onSendAgain ? <Button compact onClick={() => onSendAgain(draftFrom(data))}>Send again</Button> : undefined}
              >
                {who?.decline_reason ? `“${who.decline_reason}”` : "This request is closed for everyone on it."}
              </Notice>
            );
          })()
        : null}
      {failed.length > 0 ? (
        <Notice tone="warning" title={failed.length === 1 ? "An email was not delivered" : "Emails were not delivered"}>
          {failed.map((r) => `${r.name} (${r.email}): ${r.delivery?.error ?? "not delivered"}`).join(" · ")}
        </Notice>
      ) : null}

      <ViewerLayout>
        <ActionBar
          label="Envelope"
          actions={
            open ? (
              <>
                {waiting > 0 ? (
                  <HeadAction icon="bell" label="Remind now" disabled={remind.isPending} onClick={() => remind.mutate()} />
                ) : null}
                <HeadAction icon="cancel" label="Cancel envelope" variant="destructive" onClick={() => setConfirmCancel(true)} />
              </>
            ) : null
          }
        />
        <ViewerPane>
          {drawn.data ? (
            <PdfViewer
              url={`/api/v1/documents/${data.document_id}/versions/${data.version_id}/pdf`}
              pages={drawn.data.pages.map((p) => ({ width: p.width, height: p.height, rotation: 0 }))}
              label={`${data.document_name} as sent`}
              renderOverlay={({ page, scale }: PdfOverlayArgs) => (
                <ValuesOverlay page={page} scale={scale} font={data.font} fit={drawn.data.fit} shown={shown(data, drawn.data)} />
              )}
            />
          ) : (
            // Never a blank pane: why the document is not here, and the way to ask again. (In a
            // block of its own: the pane's last child is stretched to the pane's height.)
            <div>
              {drawn.isError ? (
                <Notice
                  tone="warning"
                  title="The document can't be shown"
                  action={<TextButton onClick={() => void drawn.refetch()}>Try again</TextButton>}
                >
                  {formError(drawn.error) ?? "Try again in a moment."}
                </Notice>
              ) : (
                <SmallText>Loading the document…</SmallText>
              )}
            </div>
          )}
        </ViewerPane>

        <DetailsPane>
          {GROUPS.map((group) => {
            const people = data.recipients.filter((r) => r.kind === group.kind);
            if (people.length === 0) return null;
            return (
              <Section key={group.kind} title={group.title} count={people.length} collapsible>
                <ItemList label={group.title} ordered={group.kind !== "copy"} cards visible={2}>
                  {people.map((recipient) =>
                    editing === recipient.id ? (
                      <Item key={recipient.id}>
                        <ChangeRecipient
                          envelopeId={envelopeId}
                          recipient={recipient}
                          onDone={(updated) => {
                            setEditing(null);
                            if (updated) refresh(updated);
                          }}
                        />
                      </Item>
                    ) : (
                      <Item
                        key={recipient.id}
                        leading={<Monogram name={recipient.name} />}
                        actions={
                          // While the envelope is open: a signer's or a copy's email can be
                          // corrected (a countersigner's is their account's); reminding and the
                          // link are for whoever holds a link, so not for someone who only
                          // receives a copy, nor a countersigner before their turn.
                          !open ? null : !LIVE.has(recipient.status) ? (
                            recipient.kind === "copy" ? (
                              <ItemActions
                                end={<IconButton icon="edit" label={`Change ${recipient.name}'s email`} onClick={() => setEditing(recipient.id)} />}
                              >
                                {null}
                              </ItemActions>
                            ) : null
                          ) : (
                            <ItemActions
                              end={
                                recipient.kind !== "countersigner" ? (
                                  <IconButton icon="edit" label={`Change ${recipient.name}'s email`} onClick={() => setEditing(recipient.id)} />
                                ) : null
                              }
                            >
                              <ItemAction disabled={remindOne.isPending} onClick={() => remindOne.mutate(recipient)}>
                                Remind
                              </ItemAction>
                              <ItemAction onClick={() => void copy(recipient)}>Copy link</ItemAction>
                              {recipient.delivery?.status === "failed" ? (
                                <ItemAction disabled={resend.isPending} onClick={() => resend.mutate(recipient.id)}>
                                  Send again
                                </ItemAction>
                              ) : null}
                            </ItemActions>
                          )
                        }
                      >
                        <ItemHead>
                          <span className={styles.name}>{recipient.name}</span>
                          <StatusPill status={RECIPIENT_PILL[recipient.status]} label={RECIPIENT_STATUS[recipient.status]} />
                        </ItemHead>
                        <span className={styles.sub}>
                          {recipient.party_label ? `${recipient.party_label} · ${recipient.email}` : recipient.email}
                        </span>
                        <span className={styles.times}>{times(recipient, data)}</span>
                        {recipient.delivery?.status === "failed" ? (
                          <span className={styles.error}>{`Email not delivered: ${recipient.delivery.error ?? "unknown reason"}`}</span>
                        ) : null}
                      </Item>
                    ),
                  )}
                </ItemList>
              </Section>
            );
          })}
          {resend.error ?? remindOne.error ? <Notice tone="warning">{formError(resend.error ?? remindOne.error)}</Notice> : null}

          <Section title="Settings" collapsible>
            <FactList
              label="Settings"
              facts={[
                { term: "Email code", value: data.require_email_code ? "Required to open" : "Off" },
                { term: "Reminders", value: `Every ${data.reminder_interval_hours} hours, up to ${data.max_reminders}` },
                data.cancelled_at
                  ? { term: "Withdrawn", value: longDay(data.cancelled_at) }
                  : { term: "Expires", value: longDay(data.expires_at) },
                ...(data.notify_emails.length > 0 ? [{ term: "Also told", value: data.notify_emails.join(", ") }] : []),
              ]}
            />
          </Section>

          <Section title="Timeline" count={data.timeline.length} collapsible>
            <div className={styles.timelineScroll}>
              <ol className={styles.timeline} aria-label="Timeline">
                {data.timeline.map((entry, index) => (
                  <li key={index} className={styles.event}>
                    <time className={styles.at} dateTime={entry.at}>
                      {new Date(entry.at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
                    </time>
                    <span className={styles.what}>{happened(entry, data)}</span>
                    {entry.by ? <span className={styles.sub}>{entry.by}</span> : null}
                  </li>
                ))}
              </ol>
            </div>
          </Section>
        </DetailsPane>
      </ViewerLayout>

      {shownLink ? (
        <Dialog
          title={`${shownLink.name}'s signing link`}
          onClose={() => setShownLink(null)}
          actions={<Button onClick={() => setShownLink(null)}>Done</Button>}
        >
          <TextField
            label="Your browser didn't allow copying. Select the link and copy it."
            readOnly
            value={shownLink.url}
            onFocus={(event) => event.currentTarget.select()}
          />
        </Dialog>
      ) : null}
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
    // ``samePerson``: the sender confirmed that one person signs as two parties (as a send asks).
    mutationFn: (samePerson: boolean) =>
      unwrap(
        api.PATCH("/api/v1/envelopes/{envelope_id}/recipients/{recipient_id}", {
          params: { path: { envelope_id: envelopeId, recipient_id: recipient.id } },
          body: {
            ...(email.trim() !== recipient.email ? { email: email.trim() } : {}),
            ...(name.trim() !== recipient.name ? { name: name.trim() } : {}),
            confirm_same_person: samePerson,
          },
        }),
      ),
    onSuccess: (updated) => onDone(updated),
  });
  const errors = fieldErrors(change.error);
  const samePerson = change.error instanceof ApiError && change.error.code === "same-person" ? (change.error.detail ?? email.trim()) : null;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    change.mutate(false);
  };
  return (
    <form className={styles.change} onSubmit={submit} aria-label={`Change ${recipient.name}`}>
      <div className={styles.pair}>
        <TextField label="Name" maxLength={120} value={name} error={errors.name} onChange={(event) => setName(event.target.value)} />
        <TextField label="Email" type="email" maxLength={254} value={email} error={errors.email} onChange={(event) => setEmail(event.target.value)} />
      </div>
      <SmallText>A new email changes their link: the one they were sent stops working.</SmallText>
      {samePerson !== null ? (
        <Notice
          tone="warning"
          title="One person on two parties"
          action={
            <Button compact loading={change.isPending} loadingLabel="Saving…" onClick={() => change.mutate(true)}>
              Change anyway
            </Button>
          }
        >
          {`${samePerson} is on another party. Change anyway if one person signs as both.`}
        </Notice>
      ) : change.error && !Object.keys(errors).length ? (
        <Notice tone="warning">{formError(change.error)}</Notice>
      ) : null}
      <div className={styles.inline}>
        <Button type="submit" variant="quiet" compact loading={change.isPending} loadingLabel="Saving…">
          Save
        </Button>
        <TextButton onClick={() => onDone(null)}>Cancel</TextButton>
      </div>
    </form>
  );
}
