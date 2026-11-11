"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, formError } from "@/shared/api/errors";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import {
  Button,
  Checkbox,
  DocumentCard,
  DocumentGrid,
  Dropzone,
  Icon,
  LinkButton,
  Notice,
  Section,
  Select,
  SmallText,
  StatusPill,
  StepDialog,
  TextButton,
  TextField,
} from "@/shared/ui";

import { useSendForm, type SendForm } from "./api";
import styles from "./bulk.module.css";
import {
  checkSheet,
  hasError,
  leftOutFile,
  readSheet,
  templateHref,
  type Batch,
  type BatchBody,
  type BatchDefaults,
  type Sheet,
  type SheetRow,
} from "./bulkApi";
import { BulkTable } from "./BulkTable";
import { LIMITED, LIMITS, outOfRange, type SendableDocument } from "./SendModal";

const STEPS = ["Template", "Upload", "Fix", "Send to", "Review"] as const;
const TEMPLATE = 0;
const UPLOAD = 1;
const FIX = 2;
const SEND_TO = 3;
const REVIEW = 4;

/** "Template" with a download mark: the spreadsheet to fill in for a template (FR-1). */
function TemplateLink({ documentId, versionId, name }: { documentId: string; versionId: string; name: string }) {
  return (
    <a
      className={styles.templateLink}
      href={templateHref({ documentId, versionId })}
      download
      aria-label={`Download the spreadsheet for ${name}`}
    >
      <Icon name="download" />
      Template
    </a>
  );
}

/** What a batch starts from: the department's countersigners and settings, as a single send does. */
function startingDefaults(form: SendForm): BatchDefaults {
  return {
    countersigners: form.countersigners.flatMap((party) =>
      party.default ? [{ party_id: party.party_id, user_id: party.default.user_id }] : [],
    ),
    copies: [],
    settings: { ...form.settings },
    time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  };
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

const plural = (count: number, one: string, many: string) => `${count.toLocaleString()} ${count === 1 ? one : many}`;

/**
 * Sending one template to many people from a spreadsheet (Bulk send LLD §9), in five steps: pick
 * the template, upload the filled spreadsheet, fix what is wrong in a table (skipped when nothing
 * is), choose what applies to every envelope, review and send. Each row becomes its own envelope,
 * checked by the same rules as a single send. Sending runs in the background; the department's
 * page shows its progress.
 */
export function BulkSendModal({
  documents,
  editHref,
  onClose,
  onSent,
  onSendOne,
}: {
  documents: readonly SendableDocument[];
  /** Where a template is edited: offered when nobody signs it, so it cannot be sent as it is. */
  editHref: (documentId: string) => string;
  onClose: () => void;
  onSent: (batch: Batch) => void;
  /** Opens the single send instead. */
  onSendOne: () => void;
}) {
  const [step, setStep] = useState<number>(TEMPLATE);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const chosen = documents.find((d) => d.id === documentId);
  const versionId = chosen?.current_version?.id ?? null;
  const form = useSendForm(documentId, versionId);
  const data = form.data;
  const version = useMemo(
    () => (documentId && versionId ? { documentId, versionId } : null),
    [documentId, versionId],
  );

  const [fileName, setFileName] = useState("");
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [fileProblems, setFileProblems] = useState<readonly string[]>([]);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);
  const [leftOut, setLeftOut] = useState<ReadonlySet<number>>(new Set());
  const [chosenDefaults, setChosenDefaults] = useState<BatchDefaults | null>(null);
  const [typed, setTyped] = useState<Partial<Record<(typeof LIMITED)[number], string>>>({});
  const [checking, setChecking] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const edited = useRef(false); // a cell changed since the rows were last checked
  const latest = useRef(0); // only the newest check's answer is kept

  const defaults = chosenDefaults ?? (data ? startingDefaults(data) : null);
  const rows = useMemo(() => sheet?.rows ?? [], [sheet]);
  const included = useMemo(() => rows.filter((row) => !leftOut.has(row.row_no)), [rows, leftOut]);
  const errors = useMemo(() => included.filter(hasError).length, [included]);
  const warnings = useMemo(
    () => included.filter((row) => !hasError(row) && (row.problems ?? []).length > 0).length,
    [included],
  );
  const nobodySigns = data !== undefined && data.signers.length === 0 && data.countersigners.length === 0;
  const settingErrors = LIMITED.filter((setting) => typed[setting] !== undefined && outOfRange(setting, typed[setting] ?? ""));
  const missingCountersigner =
    data?.countersigners.find(
      (party) =>
        !defaults?.countersigners?.some((c) => c.party_id === party.party_id) &&
        // A row may name its own; the default is needed only for rows that leave the cell empty.
        included.some((row) => !row.cells[`countersigner:${party.party_id}`]),
    ) ?? null;

  /** The rows judged again, by the server's rules, with what is chosen for the batch. */
  const check = useCallback(
    async (nextRows: readonly SheetRow[], out: ReadonlySet<number>, nextDefaults: BatchDefaults) => {
      if (!version || !sheet) return;
      const ticket = ++latest.current;
      setChecking(true);
      try {
        const kept = nextRows.filter((row) => !out.has(row.row_no));
        const answer = await checkSheet(version, {
          columns: sheet.columns.map((column) => column.key),
          rows: kept.map((row) => ({ row_no: row.row_no, cells: row.cells })),
          defaults: nextDefaults,
        });
        if (ticket !== latest.current) return;
        const judged = new Map(answer.rows.map((row) => [row.row_no, row]));
        setSheet({
          columns: answer.columns,
          // A row left out keeps what it held; it is not judged, so it shows no problems.
          rows: nextRows.map((row) => judged.get(row.row_no) ?? { ...row, problems: [] }),
          problems: answer.problems ?? [],
        });
        setReadError(null);
      } catch (error) {
        if (ticket === latest.current) setReadError(formError(error) ?? "The rows could not be checked. Try again.");
      } finally {
        if (ticket === latest.current) setChecking(false);
      }
    },
    [version, sheet],
  );

  const read = async (file: File) => {
    if (!version) return;
    setReading(true);
    setReadError(null);
    setFileProblems([]);
    try {
      const answer = await readSheet(version, file);
      setFileName(file.name);
      if (answer.rows.length === 0) {
        setSheet(null);
        setFileProblems(answer.problems ?? []);
        return;
      }
      setSheet(answer);
      setLeftOut(new Set());
      edited.current = false;
      // A clean file goes straight on: there is nothing to fix.
      setStep(answer.rows.some(hasError) ? FIX : SEND_TO);
    } catch (error) {
      setSheet(null);
      setReadError(formError(error) ?? "This file could not be read. Try again.");
    } finally {
      setReading(false);
    }
  };

  const send = useIdempotentAction<BatchBody, Batch>(
    `bulk-send:${documentId ?? ""}`,
    (body, key) =>
      unwrap(
        api.POST("/api/v1/documents/{document_id}/envelope-batches", {
          params: { path: { document_id: documentId ?? "" } },
          body,
          headers: { "Idempotency-Key": key },
        }),
      ),
    { persistInput: false }, // the rows hold people's details: never kept in the browser's storage
  );
  const sent = send.state.status === "success" ? send.state.data : null;
  const announced = useRef<string | null>(null);
  useEffect(() => {
    if (sent && announced.current !== sent.id) {
      announced.current = sent.id; // once per batch, however often the route re-renders
      onSent(sent);
    }
  }, [sent, onSent]);
  const failure = send.state.status === "error" ? send.state.error : null;
  const refused = failure instanceof ApiError && failure.code === "bulk-rows-need-fixing";
  // A batch the server refused has a row that no longer passes: the answer from outside takes the
  // dialog back to the table, with the rows checked again.
  const handled = useRef<unknown>(null);
  useEffect(() => {
    if (!refused || handled.current === failure || !defaults) return;
    handled.current = failure;
    setStep(FIX);
    void check(rows, leftOut, defaults);
  }, [refused, failure, defaults, check, rows, leftOut]);

  const changeDefaults = (next: BatchDefaults) => {
    setChosenDefaults(next);
    if (sheet) void check(rows, leftOut, next);
  };

  const blocked = (() => {
    if (step === TEMPLATE) return !documentId || !data || nobodySigns;
    if (step === UPLOAD) return !sheet;
    if (step === FIX) return errors > 0 || checking || included.length === 0;
    if (step === SEND_TO) return settingErrors.length > 0 || missingCountersigner !== null || checking || errors > 0;
    return false;
  })();

  const close = () => {
    if (sheet && !confirmLeave) setConfirmLeave(true);
    else onClose();
  };

  const submit = () => {
    if (!version || !defaults) return;
    send.run({
      version_id: version.versionId,
      file_name: fileName || "spreadsheet",
      rows: included.map((row) => ({ row_no: row.row_no, cells: row.cells })),
      defaults,
    });
  };

  const downloadLeftOut = async () => {
    if (!version || !sheet || !defaults) return;
    const out = rows.filter((row) => leftOut.has(row.row_no));
    const blob = await leftOutFile(version, {
      columns: sheet.columns.map((column) => column.key),
      rows: out.map((row) => ({ row_no: row.row_no, cells: row.cells })),
      defaults,
    });
    save(blob, "Rows left out.csv");
  };

  const colleagues = data?.colleagues ?? [];
  return (
    <StepDialog
      title="Send in bulk"
      aside={<TextButton onClick={onSendOne}>Send one instead</TextButton>}
      steps={STEPS}
      attention={errors > 0 ? { [FIX]: String(errors) } : {}}
      current={step}
      onStep={(target) => setStep(target)}
      onClose={close}
      back={step > TEMPLATE ? <TextButton onClick={() => setStep(step === SEND_TO && errors === 0 && warnings === 0 ? UPLOAD : step - 1)}>Back</TextButton> : null}
      actions={
        step < REVIEW ? (
          <Button compact disabled={blocked} onClick={() => setStep(step + 1)}>
            Next
          </Button>
        ) : (
          <Button compact arrow loading={send.isPending} loadingLabel="Sending…" disabled={errors > 0} onClick={submit}>
            {`Send ${plural(included.length, "envelope", "envelopes")}`}
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
          The rows you uploaded and fixed are not kept.
        </Notice>
      ) : null}
      {form.isError && step === TEMPLATE ? <Notice tone="warning">{formError(form.error)}</Notice> : null}
      {nobodySigns && documentId ? (
        <Notice
          tone="warning"
          title="Nobody signs this template"
          action={
            <LinkButton href={editHref(documentId)} variant="quiet">
              Edit template
            </LinkButton>
          }
        >
          Add who signs and where, then send.
        </Notice>
      ) : null}

      {step === TEMPLATE ? (
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
                      setSheet(null);
                      setFileProblems([]);
                      setLeftOut(new Set());
                      setChosenDefaults(null);
                      setTyped({});
                    }
                    setDocumentId(d.id);
                  },
                }}
                kind={d.kind === "docx" ? "DOC" : "PDF"}
                title={d.name}
                version={d.current_version ? `V${d.current_version.number}` : undefined}
                facts={d.page_count ? `${d.page_count} ${d.page_count === 1 ? "page" : "pages"}` : "Not processed yet"}
                status={d.current_version ? <StatusPill status="completed" label="Approved" /> : <StatusPill status="pending" label="Needs approval" />}
                extra={
                  d.current_version ? (
                    <TemplateLink documentId={d.id} versionId={d.current_version.id} name={d.name} />
                  ) : undefined
                }
                action={d.current_version ? "Choose" : "Approve it first"}
              />
            ))}
          </DocumentGrid>
        </Section>
      ) : null}

      {step === UPLOAD && version && chosen ? (
        <div className={styles.stack}>
          <div className={styles.headRow}>
            <p className={styles.eyebrow}>Upload the filled spreadsheet</p>
            <TemplateLink documentId={version.documentId} versionId={version.versionId} name={chosen.name} />
          </div>
          <SmallText>
            Download the spreadsheet for this template, fill one row for each envelope, and upload it here. Nothing is
            sent until you have reviewed it.
          </SmallText>
          <Dropzone
            title={reading ? "Reading the spreadsheet…" : sheet ? `${fileName} · ${plural(rows.length, "row", "rows")}` : "Drop the filled spreadsheet"}
            hint={sheet ? "Drop another file to replace it" : "XLSX or CSV, up to 1,000 rows"}
            accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
            disabled={reading}
            onFile={(file) => void read(file)}
          />
          {readError ? <Notice tone="warning">{readError}</Notice> : null}
          {fileProblems.length > 0 ? (
            <Notice tone="warning" title={`${fileName} does not match this template`}>
              <ul className={styles.problems}>
                {fileProblems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
              Download the spreadsheet again and copy your rows into it.
            </Notice>
          ) : null}
        </div>
      ) : null}

      {step === FIX && sheet ? (
        <div className={styles.stack}>
          {readError ? <Notice tone="warning">{readError}</Notice> : null}
          {refused ? (
            <Notice tone="warning" title="Some rows no longer pass">
              Something changed since you checked them. Fix the rows marked below, then send.
            </Notice>
          ) : null}
          {(sheet.problems ?? []).length > 0 ? (
            <Notice tone="warning" title="Something chosen for every envelope needs changing">
              {(sheet.problems ?? []).join(". ")}
            </Notice>
          ) : null}
          <BulkTable
            columns={sheet.columns}
            rows={rows}
            leftOut={leftOut}
            checking={checking}
            onEdit={(rowNo, key, value) => {
              edited.current = true;
              setSheet({
                ...sheet,
                rows: rows.map((row) => (row.row_no === rowNo ? { ...row, cells: { ...row.cells, [key]: value } } : row)),
              });
            }}
            onLeaveCell={() => {
              if (!edited.current || !defaults) return;
              edited.current = false;
              void check(rows, leftOut, defaults);
            }}
            onLeaveOut={(rowNo, out) => {
              const next = new Set(leftOut);
              if (out) next.add(rowNo);
              else next.delete(rowNo);
              setLeftOut(next);
              if (defaults) void check(rows, next, defaults);
            }}
          />
        </div>
      ) : null}

      {step === SEND_TO && data && defaults ? (
        <div className={styles.stack}>
          {data.countersigners.length > 0 ? (
            <Section title="Countersigners">
              <SmallText>For every row that does not name its own.</SmallText>
              <div className={styles.pair}>
                {data.countersigners.map((party) => (
                  <Select
                    key={party.party_id}
                    label={party.label}
                    placeholder="Choose a colleague"
                    options={colleagues.map((c) => ({ value: c.user_id, label: `${c.name} · ${c.email}` }))}
                    value={defaults.countersigners?.find((c) => c.party_id === party.party_id)?.user_id ?? null}
                    onChange={(userId) =>
                      changeDefaults({
                        ...defaults,
                        countersigners: [
                          ...(defaults.countersigners ?? []).filter((c) => c.party_id !== party.party_id),
                          { party_id: party.party_id, user_id: userId },
                        ],
                      })
                    }
                  />
                ))}
              </div>
              {missingCountersigner ? (
                <SmallText>{`Choose who countersigns as ${missingCountersigner.label}.`}</SmallText>
              ) : null}
            </Section>
          ) : null}
          <Section title="For every envelope">
            <Checkbox
              checked={defaults.settings.require_email_code ?? true}
              onChange={(event) =>
                changeDefaults({ ...defaults, settings: { ...defaults.settings, require_email_code: event.target.checked } })
              }
            >
              Ask each signer for a code sent to their email before they open it
            </Checkbox>
            <div className={styles.pair}>
              {LIMITED.map((setting) => {
                const text = typed[setting] ?? String(defaults.settings[setting]);
                return (
                  <TextField
                    key={setting}
                    label={LIMITS[setting].label}
                    inputMode="numeric"
                    maxLength={3}
                    value={text}
                    error={typed[setting] !== undefined ? outOfRange(setting, text) : undefined}
                    onChange={(event) => {
                      const next = event.target.value.replace(/[^0-9]/g, "");
                      setTyped((current) => ({ ...current, [setting]: next }));
                      if (outOfRange(setting, next) === undefined) {
                        changeDefaults({ ...defaults, settings: { ...defaults.settings, [setting]: Number(next) } });
                      }
                    }}
                  />
                );
              })}
            </div>
            {defaults.settings.notify_emails?.length ? (
              <SmallText>{`Also notified when one is signed: ${defaults.settings.notify_emails.join(", ")}`}</SmallText>
            ) : null}
          </Section>
          {(sheet?.problems ?? []).length > 0 ? <Notice tone="warning">{(sheet?.problems ?? []).join(". ")}</Notice> : null}
        </div>
      ) : null}

      {step === REVIEW && data && defaults && chosen ? (
        <div className={styles.stack}>
          {failure && !refused ? <Notice tone="warning">{formError(failure)}</Notice> : null}
          <Section title="Ready to send">
            <dl className={styles.facts}>
              <dt>Template</dt>
              <dd>{`${data.document_name} · V${data.version_number}`}</dd>
              <dt>Envelopes</dt>
              <dd>{`${plural(included.length, "envelope", "envelopes")}, one for each row of ${fileName}`}</dd>
              {data.countersigners.map((party) => {
                const person = colleagues.find(
                  (c) => c.user_id === defaults.countersigners?.find((d) => d.party_id === party.party_id)?.user_id,
                );
                return person ? (
                  <FactRow key={party.party_id} term={`${party.label} countersigns`} value={`${person.name}, unless a row names someone else`} />
                ) : null;
              })}
              <dt>Email code</dt>
              <dd>{defaults.settings.require_email_code === false ? "Not asked for" : "Each signer enters a code sent to their email"}</dd>
              <dt>Reminders</dt>
              <dd>{`Every ${defaults.settings.reminder_interval_hours} hours, up to ${defaults.settings.max_reminders}`}</dd>
              <dt>Expires</dt>
              <dd>{`After ${defaults.settings.expiry_days} days`}</dd>
            </dl>
          </Section>
          {warnings > 0 ? (
            <Notice title={`${plural(warnings, "row sends", "rows send")} to someone another row also sends to`}>
              Each still gets its own envelope. Go back to Fix to look at them.
            </Notice>
          ) : null}
          {leftOut.size > 0 ? (
            <Notice
              title={`${plural(leftOut.size, "row is", "rows are")} left out and will not be sent`}
              action={<TextButton onClick={() => void downloadLeftOut()}>Download them</TextButton>}
            >
              Download them to fix and send later.
            </Notice>
          ) : null}
          <SmallText>Sending runs in the background. This department&apos;s page shows how far it has got.</SmallText>
        </div>
      ) : null}
    </StepDialog>
  );
}

function FactRow({ term, value }: { term: string; value: string }) {
  return (
    <>
      <dt>{term}</dt>
      <dd>{value}</dd>
    </>
  );
}
