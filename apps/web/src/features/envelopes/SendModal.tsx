"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, formError } from "@/shared/api/errors";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import {
  Block,
  Blocks,
  Button,
  Checkbox,
  DocumentCard,
  DocumentGrid,
  Notice,
  PdfViewer,
  Section,
  Select,
  SmallText,
  StatusPill,
  StepDialog,
  TextButton,
  TextField,
  type PdfOverlayArgs,
} from "@/shared/ui";

import { useSendForm, type Envelope, type FormField, type SendForm, type SendRequest } from "./api";
import styles from "./envelopes.module.css";
import { FieldInput, refused } from "./FieldInput";
import { fitsEverywhere, kept, useFontReady, written } from "./typeset";
import { ValuesOverlay } from "./ValuesOverlay";

const STEPS = ["Template", "Details", "Signers", "Countersigners", "Review"] as const;
const DOCUMENT = 0;
const DETAILS = 1;
const SIGNERS = 2;
const COUNTERSIGNERS = 3;
const REVIEW = 4;

/** A document as the first step offers it (the route passes the department's documents). */
export type SendableDocument = {
  id: string;
  name: string;
  kind: "pdf" | "docx" | null;
  page_count: number | null;
  current_version: { id: string; number: number } | null;
};
export type Colleague = { id: string; name: string; email: string };
type Person = { name: string; email: string };
type Copy = Person & { key: string };

/** A field under a condition is asked only when its choice has that option (or the checkbox is ticked). */
function asked(field: FormField, values: Readonly<Record<string, string>>): boolean {
  if (!field.depends_on) return true;
  const given = values[field.depends_on.field_id];
  return given === field.depends_on.option || (field.depends_on.option === "checked" && given === "true");
}

/** Which step a server error is about, from its path ("signers[0].email", "fields.{id}", "parties.{id}"). */
function stepOf(path: string, form: SendForm): number {
  if (path.startsWith("fields.") || path.startsWith("values[")) return DETAILS;
  if (path.startsWith("signers[") || path.startsWith("copies[")) return SIGNERS;
  if (path.startsWith("countersigners[")) return COUNTERSIGNERS;
  if (path.startsWith("parties.")) {
    const party = path.slice("parties.".length);
    return form.countersigners.some((c) => c.party_id === party) ? COUNTERSIGNERS : SIGNERS;
  }
  return REVIEW;
}

/**
 * Sending, as a modal in five steps (Phase 7 §2): pick a document, give what you want to prefill
 * (optional, but the fields only you can fill), confirm the signers (proposed from what you typed)
 * and who receives a copy, the countersigners (the department's by default), then review the
 * document with the values in place and send. Errors from the server name the field and take the
 * modal to its step. Closing with anything filled asks first.
 */
export function SendModal({
  documents,
  colleagues,
  initialDocumentId,
  onClose,
  onSent,
}: {
  documents: readonly SendableDocument[];
  colleagues: readonly Colleague[];
  initialDocumentId?: string | undefined;
  onClose: () => void;
  onSent: (envelope: Envelope) => void;
}) {
  const [step, setStep] = useState(initialDocumentId ? DETAILS : DOCUMENT);
  const [documentId, setDocumentId] = useState<string | null>(initialDocumentId ?? null);
  const document = documents.find((d) => d.id === documentId);
  const versionId = document?.current_version?.id ?? null;
  const form = useSendForm(documentId, versionId);
  const [values, setValues] = useState<Record<string, string>>({});
  const [signers, setSigners] = useState<Record<string, Person>>({});
  const [copies, setCopies] = useState<Copy[]>([]);
  const [countersigners, setCountersigners] = useState<Record<string, string>>({});
  const [settings, setSettings] = useState<SendRequest["settings"] | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [left, setLeft] = useState<ReadonlySet<string>>(new Set()); // boxes typed in and left

  const data = form.data;
  // Asked for as soon as the form is in, so the Details step measures in it, not in a stand-in.
  const fontReady = useFontReady(data?.font);
  const touched = Object.keys(values).length > 0 || Object.keys(signers).length > 0 || copies.length > 0;

  const send = useIdempotentAction<SendRequest, Envelope>(
    `send:${documentId ?? ""}`,
    (body, key) =>
      unwrap(
        api.POST("/api/v1/documents/{document_id}/envelopes", {
          params: { path: { document_id: documentId ?? "" } },
          body,
          headers: { "Idempotency-Key": key },
        }),
      ),
    { persistInput: false },
  );

  // What each step shows, from the form once it has loaded.
  const groups = useMemo(() => {
    if (!data) return [];
    // What only the sender fills comes first: it is what blocks sending.
    const out: { label: string; hint: string; fields: FormField[] }[] = [];
    const before = data.fields.filter((f) => f.party_id === null);
    if (before.length > 0) {
      const allRequired = before.every((f) => f.required);
      out.push({
        label: "Filled in by you",
        hint: `${allRequired ? "Required to send. " : ""}Signers see these but can't change them.`,
        fields: before,
      });
    }
    for (const party of [...data.signers, ...data.countersigners]) {
      // A party's name and email come from whoever signs as it: never asked here.
      const fields = data.fields.filter((f) => f.party_id === party.party_id && !f.from_recipient);
      if (fields.length > 0)
        out.push({
          label: party.label,
          hint: "Optional. What you fill in is fixed; the rest is filled in when signing.",
          fields,
        });
    }
    return out;
  }, [data]);

  const effectiveSettings = settings ?? (data ? { ...data.settings } : null);
  const firstSigner = data?.signers[0] ? signers[data.signers[0].party_id] : undefined;
  const effectiveTitle =
    title ?? (data ? (firstSigner?.name ? `${data.document_name} · ${firstSigner.name}` : data.document_name) : "");

  /**
   * A typed value wider than its box even at the smallest size (the server refuses it too). Judged
   * only in the envelope's own font, as the server keeps and writes the value; until the font is
   * in, nothing is called too long (Send still checks).
   */
  const tooLong = (f: FormField): boolean => {
    const value = values[f.id]?.trim();
    if (!data || !fontReady || !value || f.holds === "checkbox" || f.holds === "choice" || !asked(f, values)) return false;
    return !fitsEverywhere(written(f.holds, kept(f.holds, value), f.format), f.places, data.font, data.fit);
  };

  /** A day or a year the server would refuse, in its words. */
  const unkept = (f: FormField): string | undefined => (asked(f, values) ? refused(f.holds, values[f.id]?.trim() ?? "") : undefined);

  /** Who signs as a party, as chosen so far: a signer typed in, or the countersigning colleague. */
  const personOf = (partyId: string): Person | undefined => {
    const signer = signers[partyId];
    if (signer) return signer;
    const firm = data?.countersigners.find((c) => c.party_id === partyId);
    const userId = firm ? countersignerOf(partyId, firm.default?.user_id) : "";
    const colleague = colleagues.find((c) => c.id === userId);
    return colleague ? { name: colleague.name, email: colleague.email } : undefined;
  };

  const countersignerOf = (partyId: string, fallback: string | null | undefined) => countersigners[partyId] ?? fallback ?? "";

  // What blocks Next on each step (the server checks everything again on Send).
  const missing = (() => {
    if (!data) return step === DOCUMENT ? !documentId : true;
    if (step === DOCUMENT) return !documentId;
    if (step === DETAILS)
      return data.fields.some(
        (f) => (f.required && asked(f, values) && !values[f.id]?.trim()) || tooLong(f) || unkept(f) !== undefined,
      );
    if (step === SIGNERS)
      return (
        data.signers.some((s) => !signers[s.party_id]?.name.trim() || !signers[s.party_id]?.email.trim()) ||
        copies.some((c) => !c.name.trim() || !c.email.trim())
      );
    if (step === COUNTERSIGNERS)
      return data.countersigners.some((c) => !countersignerOf(c.party_id, c.default?.user_id));
    return false;
  })();

  const submit = (confirm: boolean) => {
    if (!data || !effectiveSettings || !versionId) return;
    const body: SendRequest = {
      version_id: versionId,
      title: effectiveTitle.trim() || null,
      signers: data.signers.map((s) => ({
        party_id: s.party_id,
        name: signers[s.party_id]?.name.trim() ?? "",
        email: signers[s.party_id]?.email.trim() ?? "",
      })),
      countersigners: data.countersigners.map((c) => ({
        party_id: c.party_id,
        user_id: countersignerOf(c.party_id, c.default?.user_id),
      })),
      copies: copies.map(({ name, email }) => ({ name: name.trim(), email: email.trim() })),
      values: data.fields
        .filter((f) => asked(f, values) && values[f.id]?.trim())
        .map((f) => ({ field_id: f.id, value: values[f.id] ?? "" })),
      settings: effectiveSettings,
      confirm_same_person: confirm,
      // The sender's time zone: the envelope's emails give its dates as the sender sees them here.
      time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
    send.run(body);
  };

  // The answer: the envelope (the route opens it), one person on two parties (ask), or each
  // problem named (shown on its field; the review step lists the steps to go back to).
  const sent = send.state.status === "success" ? send.state.data : null;
  const announced = useRef<string | null>(null);
  useEffect(() => {
    if (sent && announced.current !== sent.id) {
      announced.current = sent.id; // once per envelope, however often the route re-renders
      onSent(sent);
    }
  }, [sent, onSent]);
  const failure = send.state.status === "error" ? send.state.error : null;
  const samePerson = failure instanceof ApiError && failure.code === "same-person" ? (failure.detail ?? "") : null;
  const errors: Record<string, string> =
    failure instanceof ApiError && failure.problem.errors
      ? Object.fromEntries(failure.problem.errors.map((e) => [e.field, e.message]))
      : {};
  const errorSteps = data ? [...new Set(Object.keys(errors).map((path) => stepOf(path, data)))].sort() : [];

  const close = () => (touched && !sent ? setConfirmLeave(true) : onClose());
  const fieldError = (id: string) => errors[`fields.${id}`];
  const next = () => {
    setStep(step + 1);
  };

  return (
    <StepDialog
      title={data ? `Send ${data.document_name}` : "New envelope"}
      steps={STEPS}
      current={step}
      onStep={(target) => setStep(target)}
      onClose={close}
      back={step > (initialDocumentId ? DETAILS : DOCUMENT) ? <TextButton onClick={() => setStep(step - 1)}>Back</TextButton> : null}
      actions={
        step < REVIEW ? (
          <Button compact disabled={missing} onClick={next}>
            Next
          </Button>
        ) : (
          <Button
            compact
            arrow
            loading={send.isPending}
            loadingLabel="Sending…"
            disabled={!data}
            onClick={() => submit(false)}
          >
            Send envelope
          </Button>
        )
      }
    >
      {confirmLeave ? (
        <Notice
          tone="warning"
          title="Close without sending?"
          action={
            <span className={styles.inline}>
              <Button variant="destructive" compact onClick={onClose}>
                Close
              </Button>
              <TextButton onClick={() => setConfirmLeave(false)}>Keep going</TextButton>
            </span>
          }
        >
          What you filled in is not kept.
        </Notice>
      ) : null}
      {form.isError && step === DOCUMENT ? <Notice tone="warning">{formError(form.error)}</Notice> : null}

      {step === DOCUMENT ? (
        <Section title="Choose the template">
          {documents.length === 0 ? <SmallText>This department has no templates yet.</SmallText> : null}
          <DocumentGrid label="Templates">
            {documents.map((d) => (
              <DocumentCard
                key={d.id}
                choose={{
                  chosen: d.id === documentId,
                  disabled: !d.current_version,
                  onChoose: () => {
                    if (d.id !== documentId) {
                      setValues({});
                      setSigners({});
                      setCountersigners({});
                      setSettings(null);
                      setTitle(null);
                    }
                    setDocumentId(d.id);
                  },
                }}
                kind={d.kind === "docx" ? "DOC" : "PDF"}
                title={d.name}
                version={d.current_version ? `V${d.current_version.number}` : undefined}
                facts={d.page_count ? `${d.page_count} ${d.page_count === 1 ? "page" : "pages"}` : "Not processed yet"}
                status={d.current_version ? <StatusPill status="completed" label="Approved" /> : <StatusPill status="pending" label="Needs approval" />}
                action={d.current_version ? "Choose" : "Approve it first"}
              />
            ))}
          </DocumentGrid>
        </Section>
      ) : null}

      {step !== DOCUMENT && !data ? (
        // Never a blank step: why there is nothing to fill in yet.
        <div className={styles.steps}>
          {document && !document.current_version ? (
            <Notice tone="warning" title={`${document.name} needs approval`}>
              Only an approved version can be sent. Approve a version on the template&apos;s page, then send it.
            </Notice>
          ) : form.error ? (
            <Notice tone="warning" title="This template can't be sent right now">
              {formError(form.error) ?? "Try again in a moment."}
            </Notice>
          ) : (
            <SmallText>Loading the template&apos;s fields…</SmallText>
          )}
        </div>
      ) : null}

      {step === DETAILS && data ? (
        <div className={styles.steps}>
          {groups.length > 0 ? (
            <Blocks>
              {groups.map((group) => {
                const mixed = group.fields.some((f) => f.required) && !group.fields.every((f) => f.required);
                return (
                  <Block key={group.label} title={group.label} hint={group.hint}>
                    {group.fields
                      .filter((f) => asked(f, values))
                      .map((f) => (
                        <FieldInput
                          key={f.id}
                          field={f}
                          markRequired={mixed}
                          value={values[f.id] ?? ""}
                          error={
                            fieldError(f.id) ??
                            (tooLong(f) ? "Too long for its box" : left.has(f.id) ? unkept(f) : undefined)
                          }
                          onBlur={() => setLeft((current) => (current.has(f.id) ? current : new Set(current).add(f.id)))}
                          onChange={(value) => setValues((current) => ({ ...current, [f.id]: value }))}
                        />
                      ))}
                  </Block>
                );
              })}
            </Blocks>
          ) : (
            <SmallText>Nothing to fill in before sending.</SmallText>
          )}
        </div>
      ) : null}

      {step === SIGNERS && data ? (
        <div className={styles.steps}>
          <Section title="Who signs">
            {data.signers.map((signer, index) => {
              const person = signers[signer.party_id] ?? { name: "", email: "" };
              const set = (patch: Partial<Person>) =>
                setSigners((current) => ({ ...current, [signer.party_id]: { ...person, ...patch } }));
              return (
                <div key={signer.party_id} className={styles.person}>
                  <p className={styles.personLabel}>{`Signer ${index + 1} · ${signer.kind_label ?? signer.label}`}</p>
                  <div className={styles.pair}>
                    <TextField
                      label="Name"
                      required
                      maxLength={120}
                      value={person.name}
                      error={errors[`signers[${index}].name`]}
                      onChange={(event) => set({ name: event.target.value })}
                    />
                    <TextField
                      label="Email"
                      type="email"
                      required
                      maxLength={254}
                      value={person.email}
                      error={errors[`signers[${index}].email`] ?? errors[`parties.${signer.party_id}`]}
                      onChange={(event) => set({ email: event.target.value })}
                    />
                  </div>
                </div>
              );
            })}
          </Section>
          <Section title="Receives a copy">
            <SmallText>People who don&apos;t sign but get the completed document.</SmallText>
            {copies.map((copy, index) => (
              <div key={copy.key} className={styles.pair}>
                <TextField
                  label="Name"
                  maxLength={120}
                  value={copy.name}
                  error={errors[`copies[${index}].name`]}
                  onChange={(event) =>
                    setCopies((current) => current.map((c) => (c.key === copy.key ? { ...c, name: event.target.value } : c)))
                  }
                />
                <TextField
                  label="Email"
                  type="email"
                  maxLength={254}
                  value={copy.email}
                  error={errors[`copies[${index}].email`]}
                  onChange={(event) =>
                    setCopies((current) => current.map((c) => (c.key === copy.key ? { ...c, email: event.target.value } : c)))
                  }
                />
                <TextButton onClick={() => setCopies((current) => current.filter((c) => c.key !== copy.key))}>
                  Remove
                </TextButton>
              </div>
            ))}
            {copies.length < 10 ? (
              <div>
                <TextButton onClick={() => setCopies((current) => [...current, { key: crypto.randomUUID(), name: "", email: "" }])}>
                  + Add someone
                </TextButton>
              </div>
            ) : null}
          </Section>
        </div>
      ) : null}

      {step === COUNTERSIGNERS && data ? (
        <div className={styles.steps}>
          <Section title="Who countersigns">
            {data.countersigners.length === 0 ? (
              <SmallText>Nobody countersigns this template: the signers&apos; signatures complete it.</SmallText>
            ) : null}
            {data.countersigners.map((party, index) => {
              const chosen = countersignerOf(party.party_id, party.default?.user_id);
              const person = colleagues.find((c) => c.id === chosen);
              return (
                <div key={party.party_id} className={styles.person}>
                  <Select
                    label={`Countersigner ${index + 1} · ${party.label}`}
                    options={colleagues.map((c) => ({ value: c.id, label: `${c.name} · ${c.email}` }))}
                    value={chosen || null}
                    placeholder="Choose a colleague"
                    onChange={(value) => setCountersigners((current) => ({ ...current, [party.party_id]: value }))}
                  />
                  {person ? <SmallText>{`${person.name} is emailed once every signer has signed.`}</SmallText> : null}
                  {errors[`parties.${party.party_id}`] ?? errors[`countersigners[${index}].user_id`] ? (
                    <p className={styles.error} role="alert">
                      {errors[`parties.${party.party_id}`] ?? errors[`countersigners[${index}].user_id`]}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </Section>
        </div>
      ) : null}

      {step === REVIEW && data && effectiveSettings && document && versionId ? (
        <div className={styles.review}>
          <div className={styles.preview}>
            <PdfViewer
              url={`/api/v1/documents/${document.id}/versions/${versionId}/pdf`}
              pages={data.pages.map((p) => ({ width: p.width, height: p.height, rotation: 0 }))}
              label={`${data.document_name} with the values you filled in`}
              renderOverlay={({ page, scale }: PdfOverlayArgs) => (
                <ValuesOverlay
                  page={page}
                  scale={scale}
                  font={data.font}
                  fit={data.fit}
                  shown={data.fields.flatMap((f) => {
                    if (f.from_recipient && f.party_id) {
                      const person = personOf(f.party_id);
                      if (!person) return [];
                      // The email is theirs from the send; the name is the one they sign as, later.
                      return f.from_recipient === "email"
                        ? [{ places: f.places, holds: f.holds, value: person.email }]
                        : [{ places: f.places, holds: f.holds, value: person.name, atSigning: true }];
                    }
                    const value = values[f.id]?.trim();
                    // As the server keeps it, so the preview is what the signed PDF prints.
                    return asked(f, values) && value
                      ? [{ places: f.places, holds: f.holds, value: kept(f.holds, value), format: f.format }]
                      : [];
                  })}
                />
              )}
            />
          </div>
          <div className={styles.summary}>
            {samePerson !== null ? (
              <Notice
                tone="warning"
                title="One person on two parties"
                action={
                  <Button compact loading={send.isPending} loadingLabel="Sending…" onClick={() => submit(true)}>
                    Send anyway
                  </Button>
                }
              >
                {`${samePerson} is on two parties. Send anyway if one person signs as both.`}
              </Notice>
            ) : null}
            {errorSteps.length > 0 ? (
              <Notice
                tone="warning"
                title="Some details need a change"
                action={
                  <span className={styles.inline}>
                    {errorSteps.map((target) => (
                      <TextButton key={target} onClick={() => setStep(target)}>
                        {`Go to ${STEPS[target]}`}
                      </TextButton>
                    ))}
                  </span>
                }
              >
                Each one is marked on its field.
              </Notice>
            ) : failure && samePerson === null ? (
              <Notice tone="warning">{formError(failure)}</Notice>
            ) : null}
            <TextField label="Title" maxLength={120} value={effectiveTitle} onChange={(event) => setTitle(event.target.value)} />
            <Section title="Recipients">
              <ul className={styles.list}>
                {data.signers.map((s, i) => (
                  <li key={s.party_id}>{`Signer ${i + 1}: ${signers[s.party_id]?.name ?? ""} · ${signers[s.party_id]?.email ?? ""}`}</li>
                ))}
                {data.countersigners.map((c, i) => {
                  const person = colleagues.find((p) => p.id === countersignerOf(c.party_id, c.default?.user_id));
                  return <li key={c.party_id}>{`Countersigner ${i + 1}: ${person?.name ?? ""}`}</li>;
                })}
                {copies.map((copy) => (
                  <li key={copy.key}>{`Receives a copy: ${copy.name} · ${copy.email}`}</li>
                ))}
              </ul>
            </Section>
            <Section title="Settings">
              <Checkbox
                checked={effectiveSettings.require_email_code ?? true}
                onChange={(event) => setSettings({ ...effectiveSettings, require_email_code: event.target.checked })}
              >
                Ask for a code sent to their email before they sign
              </Checkbox>
              <details className={styles.more}>
                <summary>{`Reminds every ${effectiveSettings.reminder_interval_hours} hours, up to ${effectiveSettings.max_reminders} · expires in ${effectiveSettings.expiry_days} days`}</summary>
                <div className={styles.pair}>
                  <TextField
                    label="Remind every (hours)"
                    type="number"
                    min={1}
                    max={720}
                    value={String(effectiveSettings.reminder_interval_hours)}
                    error={errors["settings.reminder_interval_hours"]}
                    onChange={(event) => setSettings({ ...effectiveSettings, reminder_interval_hours: Number(event.target.value) })}
                  />
                  <TextField
                    label="Reminders at most"
                    type="number"
                    min={0}
                    max={20}
                    value={String(effectiveSettings.max_reminders)}
                    onChange={(event) => setSettings({ ...effectiveSettings, max_reminders: Number(event.target.value) })}
                  />
                  <TextField
                    label="Expires after (days)"
                    type="number"
                    min={1}
                    max={365}
                    value={String(effectiveSettings.expiry_days)}
                    onChange={(event) => setSettings({ ...effectiveSettings, expiry_days: Number(event.target.value) })}
                  />
                </div>
                {effectiveSettings.notify_emails?.length ? (
                  <SmallText>{`Also notified when it is signed: ${effectiveSettings.notify_emails.join(", ")}`}</SmallText>
                ) : null}
              </details>
            </Section>
          </div>
        </div>
      ) : null}
    </StepDialog>
  );
}
