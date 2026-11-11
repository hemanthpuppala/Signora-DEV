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
  type SheetColumn,
  type SheetRow,
} from "./bulkApi";
import { BulkTable } from "./BulkTable";
import { LIMITED, LIMITS, outOfRange, type SendableDocument } from "./SendModal";

const STEPS = ["Template", "Upload", "Fix", "Review"] as const;
const TEMPLATE = 0;
const UPLOAD = 1;
const FIX = 2;
const REVIEW = 3;
/** How long after the last change the rows are checked: one request for a burst of edits. */
const CHECK_DELAY_MS = 250;

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

/** What a batch starts from: the department's settings, as a single send does. */
function startingDefaults(form: SendForm): BatchDefaults {
  return {
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
 * Sending one template to many people from a spreadsheet (Bulk send LLD §9), in four steps: pick
 * the template, upload the filled spreadsheet, fix what is wrong in a table (skipped when nothing
 * is), review and send. Each row becomes its own envelope, checked by the same rules as a single
 * send, and names its own signers and countersigner. Sending runs in the background; the
 * department's page shows its progress.
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
  const [columns, setColumns] = useState<readonly SheetColumn[]>([]);
  const [rows, setRows] = useState<readonly SheetRow[] | null>(null);
  const [batchProblems, setBatchProblems] = useState<readonly string[]>([]);
  const [fileProblems, setFileProblems] = useState<readonly string[]>([]);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);
  const [leftOut, setLeftOut] = useState<ReadonlySet<number>>(new Set());
  const [chosenDefaults, setChosenDefaults] = useState<BatchDefaults | null>(null);
  const [typed, setTyped] = useState<Partial<Record<(typeof LIMITED)[number], string>>>({});
  const [checking, setChecking] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);

  const defaults = chosenDefaults ?? (data ? startingDefaults(data) : null);

  // What a check reads when it runs, kept beside the state so a check started from a timer or
  // from the handler that made the change sees that change, never the render before it.
  const live = useRef<{
    rows: readonly SheetRow[];
    columns: readonly SheetColumn[];
    leftOut: ReadonlySet<number>;
    defaults: BatchDefaults | null;
    /** How many times each row has been edited: an answer about an older edit is not applied. */
    edits: Map<number, number>;
    dirty: boolean; // a cell was typed in since the last check was asked for
    timer: ReturnType<typeof setTimeout> | null;
    ticket: number; // only the newest check's answer is used
    check: () => Promise<void>; // the check as it is now, for the timer to run
  }>({
    rows: [],
    columns: [],
    leftOut: new Set(),
    defaults: null,
    edits: new Map(),
    dirty: false,
    timer: null,
    ticket: 0,
    check: async () => {},
  });
  useEffect(() => {
    live.current.defaults = defaults;
  }, [defaults]);
  useEffect(() => {
    const state = live.current;
    return () => {
      if (state.timer) clearTimeout(state.timer);
    };
  }, []);

  /** Ask for a check shortly: a burst of changes is one request. */
  const schedule = useCallback(() => {
    const state = live.current;
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(() => {
      state.timer = null;
      void state.check();
    }, CHECK_DELAY_MS);
  }, []);

  const putRows = useCallback((next: readonly SheetRow[]) => {
    live.current.rows = next;
    setRows(next);
  }, []);

  /** The rows judged again by the server's rules. Its answer never undoes what was typed since. */
  const check = useCallback(async () => {
    const state = live.current;
    if (!version || !state.defaults || state.rows.length === 0) return;
    const ticket = ++state.ticket;
    state.dirty = false;
    const asked = new Map(state.edits);
    const kept = state.rows.filter((row) => !state.leftOut.has(row.row_no));
    setChecking(true);
    try {
      const answer = await checkSheet(version, {
        columns: state.columns.map((column) => column.key),
        rows: kept.map((row) => ({ row_no: row.row_no, cells: row.cells })),
        defaults: state.defaults,
      });
      if (ticket !== state.ticket) return; // a newer check is on its way
      const judged = new Map(answer.rows.map((row) => [row.row_no, row]));
      let stale = false;
      putRows(
        state.rows.map((row) => {
          const verdict = judged.get(row.row_no);
          // A row left out is not judged. A row edited since this check was asked for keeps
          // what it holds now; the next check judges it.
          if (!verdict) return state.leftOut.has(row.row_no) ? { ...row, problems: [] } : row;
          if (state.edits.get(row.row_no) !== asked.get(row.row_no)) {
            stale = true;
            return row;
          }
          return verdict;
        }),
      );
      live.current.columns = answer.columns;
      setColumns(answer.columns);
      setBatchProblems(answer.problems ?? []);
      setReadError(null);
      if (stale) schedule();
    } catch (error) {
      if (ticket === state.ticket) setReadError(formError(error) ?? "The rows could not be checked. Try again.");
    } finally {
      if (ticket === state.ticket) setChecking(false);
    }
  }, [version, putRows, schedule]);

  useEffect(() => {
    live.current.check = check;
  }, [check]);

  const editCell = useCallback(
    (rowNo: number, key: string, value: string, done: boolean) => {
      const state = live.current;
      state.edits.set(rowNo, (state.edits.get(rowNo) ?? 0) + 1);
      putRows(state.rows.map((row) => (row.row_no === rowNo ? { ...row, cells: { ...row.cells, [key]: value } } : row)));
      if (done) schedule();
      else state.dirty = true;
    },
    [putRows, schedule],
  );
  const leaveCell = useCallback(() => {
    if (live.current.dirty) schedule();
  }, [schedule]);
  const leaveOut = useCallback((rowNo: number, out: boolean) => {
    const next = new Set(live.current.leftOut);
    if (out) next.add(rowNo);
    else next.delete(rowNo);
    live.current.leftOut = next;
    setLeftOut(next);
    schedule();
  }, [schedule]);
  const fillEmpty = useCallback(
    (key: string, value: string) => {
      const state = live.current;
      putRows(
        state.rows.map((row) => {
          if (state.leftOut.has(row.row_no) || row.cells[key]) return row;
          state.edits.set(row.row_no, (state.edits.get(row.row_no) ?? 0) + 1);
          return { ...row, cells: { ...row.cells, [key]: value } };
        }),
      );
      schedule();
    },
    [putRows, schedule],
  );

  const all = useMemo(() => rows ?? [], [rows]);
  const included = useMemo(() => all.filter((row) => !leftOut.has(row.row_no)), [all, leftOut]);
  const errors = useMemo(() => included.filter(hasError).length, [included]);
  const warnings = useMemo(
    () => included.filter((row) => !hasError(row) && (row.problems ?? []).length > 0).length,
    [included],
  );
  const nobodySigns = data !== undefined && data.signers.length === 0 && data.countersigners.length === 0;
  const settingErrors = LIMITED.filter((setting) => typed[setting] !== undefined && outOfRange(setting, typed[setting] ?? ""));

  const read = async (file: File) => {
    if (!version) return;
    setReading(true);
    setReadError(null);
    setFileProblems([]);
    try {
      const answer = await readSheet(version, file);
      setFileName(file.name);
      if (answer.rows.length === 0) {
        setRows(null);
        live.current.rows = [];
        setFileProblems(answer.problems ?? []);
        return;
      }
      const state = live.current;
      state.columns = answer.columns;
      state.leftOut = new Set();
      state.edits = new Map();
      state.dirty = false;
      state.ticket++; // an answer still on its way was about the file before this one
      setColumns(answer.columns);
      putRows(answer.rows);
      setBatchProblems(answer.problems ?? []);
      setLeftOut(state.leftOut);
      // A clean file goes straight to the review: there is nothing to fix.
      setStep(answer.rows.some(hasError) ? FIX : REVIEW);
    } catch (error) {
      setRows(null);
      live.current.rows = [];
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
    if (!refused || handled.current === failure) return;
    handled.current = failure;
    setStep(FIX);
    void check();
  }, [refused, failure, check]);

  const changeDefaults = (next: BatchDefaults) => {
    setChosenDefaults(next);
    live.current.defaults = next;
    schedule();
  };

  const blocked = (() => {
    if (step === TEMPLATE) return !documentId || !data || nobodySigns;
    if (step === UPLOAD) return rows === null;
    if (step === FIX) return errors > 0 || checking || included.length === 0;
    return false;
  })();
  const cannotSend = errors > 0 || checking || included.length === 0 || settingErrors.length > 0 || batchProblems.length > 0;

  const close = () => {
    if (rows !== null && !confirmLeave) setConfirmLeave(true);
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
    if (!version || !defaults) return;
    const blob = await leftOutFile(version, {
      columns: columns.map((column) => column.key),
      rows: all.filter((row) => leftOut.has(row.row_no)).map((row) => ({ row_no: row.row_no, cells: row.cells })),
      defaults,
    });
    save(blob, "Rows left out.csv");
  };

  // Who countersigns, as the rows say: each party's colleagues and how many rows name each.
  const countersigning = useMemo(() => {
    if (!data) return [];
    const nameOf = new Map(data.colleagues.map((colleague) => [colleague.email, colleague.name]));
    return data.countersigners.map((party) => {
      const counts = new Map<string, number>();
      for (const row of included) {
        const email = row.cells[`countersigner:${party.party_id}`];
        if (email) counts.set(email, (counts.get(email) ?? 0) + 1);
      }
      const people = [...counts].map(([email, count]) =>
        counts.size === 1 ? (nameOf.get(email) ?? email) : `${nameOf.get(email) ?? email} (${plural(count, "row", "rows")})`,
      );
      return { label: party.label, people: people.join(", ") };
    });
  }, [data, included]);

  return (
    <StepDialog
      title="Send in bulk"
      aside={<TextButton onClick={onSendOne}>Send one instead</TextButton>}
      steps={STEPS}
      attention={errors > 0 ? { [FIX]: String(errors) } : {}}
      current={step}
      onStep={(target) => setStep(target)}
      onClose={close}
      back={step > TEMPLATE ? <TextButton onClick={() => setStep(step - 1)}>Back</TextButton> : null}
      actions={
        step < REVIEW ? (
          <Button compact disabled={blocked} onClick={() => setStep(step + 1)}>
            Next
          </Button>
        ) : (
          <Button compact arrow loading={send.isPending} loadingLabel="Sending…" disabled={cannotSend} onClick={submit}>
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
                      setRows(null);
                      live.current.rows = [];
                      setFileProblems([]);
                      setLeftOut(new Set());
                      live.current.leftOut = new Set();
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
            title={reading ? "Reading the spreadsheet…" : rows ? `${fileName} · ${plural(all.length, "row", "rows")}` : "Drop the filled spreadsheet"}
            hint={rows ? "Drop another file to replace it" : "XLSX or CSV, up to 1,000 rows"}
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

      {step === FIX && rows ? (
        <div className={styles.stack}>
          {readError ? <Notice tone="warning">{readError}</Notice> : null}
          {refused ? (
            <Notice tone="warning" title="Some rows no longer pass">
              Something changed since you checked them. Fix the rows marked below, then send.
            </Notice>
          ) : null}
          <BulkTable
            columns={columns}
            rows={all}
            leftOut={leftOut}
            checking={checking}
            onEdit={editCell}
            onLeaveCell={leaveCell}
            onLeaveOut={leaveOut}
            onFillEmpty={fillEmpty}
          />
        </div>
      ) : null}

      {step === REVIEW && data && defaults && chosen ? (
        <div className={styles.stack}>
          {failure && !refused ? <Notice tone="warning">{formError(failure)}</Notice> : null}
          {batchProblems.length > 0 ? (
            <Notice tone="warning" title="Something set for every envelope needs changing">
              {batchProblems.join(". ")}
            </Notice>
          ) : null}
          <Section title="Ready to send">
            <dl className={styles.facts}>
              <dt>Template</dt>
              <dd>{`${data.document_name} · V${data.version_number}`}</dd>
              <dt>Envelopes</dt>
              <dd>{`${plural(included.length, "envelope", "envelopes")}, one for each row of ${fileName}`}</dd>
              {countersigning.map((party) =>
                party.people ? <FactRow key={party.label} term={`${party.label} countersigns`} value={party.people} /> : null,
              )}
            </dl>
          </Section>
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
