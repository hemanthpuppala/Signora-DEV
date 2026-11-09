"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import {
  Button,
  Dialog,
  Dropzone,
  HeadRow,
  Heading1,
  Notice,
  Section,
  TextArea,
  TextButton,
  TextField,
} from "@/shared/ui";
import {
  clearHandOff,
  documentKey,
  documentsKey,
  formatBytes,
  handedOffFile,
  uploadFile,
  type DepartmentRef,
  type Upload,
} from "./api";
import { useDocumentLimits } from "./limits";
import styles from "./upload.module.css";

type Phase = "uploading" | "question" | "ready" | "creating" | "failed" | "cancelled";

type Row = {
  key: string;
  file: File;
  phase: Phase;
  progress: number;
  upload: Upload | null;
  name: string;
  instructions: string;
  allowDuplicate: boolean;
  /** Reused if "Add document" is pressed again after a lost connection: never two documents. */
  idempotencyKey: string;
  message: string | null;
  /** Whether a failure is worth repeating; Try again sends the file again. */
  canRetry: boolean;
  nameError: string | null;
  instructionsError: string | null;
};

const CANCELLED = "Upload cancelled. Nothing was added.";

function newRow(file: File, tooLargeMessage: string | null): Row {
  return {
    key: crypto.randomUUID(),
    file,
    phase: tooLargeMessage ? "failed" : "uploading",
    progress: 0,
    upload: null,
    name: "",
    instructions: "",
    allowDuplicate: false,
    idempotencyKey: crypto.randomUUID(),
    message: tooLargeMessage,
    canRetry: false,
    nameError: null,
    instructionsError: null,
  };
}

/** The size refusal, stating the limit the server enforces (from /meta, never written here). */
function tooLargeMessage(maxBytes: number | undefined): string {
  return maxBytes ? `Upload a file of ${formatBytes(maxBytes)} or less` : "This file is too large. Upload a smaller one";
}

/** Why an upload failed, and whether sending it again could work (no answer, a wait, a fault). */
function uploadFailure(error: unknown, maxBytes: number | undefined): Pick<Row, "message" | "canRetry"> {
  if (!(error instanceof ApiError)) return { message: "The upload didn't finish. Try again", canRetry: true };
  // The API's 413, or the proxy's bare one when a body passes its own limit.
  if (error.status === 413) return { message: tooLargeMessage(maxBytes), canRetry: false };
  // The hourly limit states its wait; a server fault gives its reference.
  if (error.status === 429 || error.status >= 500) {
    return { message: formError(error) ?? error.problem.title, canRetry: true };
  }
  return { message: error.problem.title, canRetry: false }; // the file itself is refused
}

/**
 * Screen 11 (Phase 4 LLD §6.2): one document at a time (owner decision). The dropzone until a file
 * is chosen, then that file in its place: its progress, name, instructions for the AI and duplicate
 * question. Once added, the person is taken to the document's page, which shows its steps.
 */
const isAbort = (error: unknown) => error instanceof DOMException && error.name === "AbortError";

export function UploadPage({ department }: { department: DepartmentRef }) {
  const departmentId = department.id;
  const canUpload = department.status !== "archived" && department.access === "edit";
  const queryClient = useQueryClient();
  const router = useRouter();
  const limits = useDocumentLimits();
  const { maxBytes } = limits;
  // A file handed over from the department or new-department page starts uploading at once.
  const [row, setRow] = useState<Row | null>(() => {
    const file = handedOffFile(departmentId);
    return file ? newRow(file, null) : null;
  });

  // Only the row it was meant for: a late answer for a removed or retried file changes nothing.
  const update = useCallback((key: string, patch: Partial<Row>) => {
    setRow((current) => (current?.key === key ? { ...current, ...patch } : current));
  }, []);

  // The transfer still running, so cancelling or leaving the page stops it.
  const running = useRef<{ key: string; controller: AbortController } | null>(null);

  // Starts the transfer; its progress and result arrive later, as events.
  const transfer = useCallback(
    (key: string, file: File) => {
      const controller = new AbortController();
      running.current = { key, controller };
      uploadFile(departmentId, file, (progress) => update(key, { progress }), controller.signal)
        .then((upload) =>
          setRow((current) =>
            current?.key === key
              ? {
                  ...current,
                  upload,
                  // Sent again after it expired: keep the name the person already typed.
                  name: current.name || upload.suggested_name,
                  phase: upload.duplicate && !current.allowDuplicate ? "question" : "ready",
                }
              : current,
          ),
        )
        .catch((error: unknown) => {
          if (!isAbort(error)) update(key, { phase: "failed", ...uploadFailure(error, maxBytes) });
        })
        .finally(() => {
          if (running.current?.controller === controller) running.current = null;
        });
    },
    [departmentId, maxBytes, update],
  );

  // The row's transfer, once per key (effects may run twice in development). Nothing is sent where
  // the person can't add documents: the page explains that instead.
  const started = useRef<string | null>(null);
  useEffect(() => {
    clearHandOff(departmentId);
    if (!canUpload || !row || row.phase !== "uploading" || started.current === row.key) return;
    started.current = row.key;
    transfer(row.key, row.file);
  }, [canUpload, departmentId, row, transfer]);

  // Leaving the page stops an upload still running (a development remount starts it again).
  useEffect(
    () => () => {
      running.current?.controller.abort();
      running.current = null;
      started.current = null;
    },
    [],
  );

  const remove = () => {
    running.current?.controller.abort();
    running.current = null;
    setRow(null);
  };

  const addFile = (file: File) => {
    const tooLarge = maxBytes !== undefined && file.size > maxBytes;
    setRow(newRow(file, tooLarge ? tooLargeMessage(maxBytes) : null)); // the effect starts its transfer
  };

  // A new key makes the effect above start a fresh transfer for the same file; a new upload is a
  // new request to add it, so it gets a new idempotency key too.
  const retry = (row: Row) =>
    update(row.key, {
      key: crypto.randomUUID(),
      phase: "uploading",
      progress: 0,
      upload: null,
      message: null,
      canRetry: false,
      idempotencyKey: crypto.randomUUID(),
    });

  const create = (row: Row) => {
    if (!row.upload) return;
    update(row.key, { phase: "creating", message: null, nameError: null, instructionsError: null });
    unwrap(
      api.POST("/api/v1/departments/{department_id}/documents", {
        params: { path: { department_id: departmentId } },
        headers: { "Idempotency-Key": row.idempotencyKey },
        body: {
          name: row.name,
          ai_instructions: row.instructions,
          upload_id: row.upload.id,
          allow_duplicate: row.allowDuplicate,
        },
      }),
    )
      .then((document) => {
        // Added: on to its page, which shows its steps until it is ready (Phase 5 §6.3).
        queryClient.setQueryData(documentKey(document.id), document);
        void queryClient.invalidateQueries({ queryKey: documentsKey(departmentId) });
        router.replace(`/departments/${departmentId}/documents/${document.id}`);
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "document-name-taken") {
          // A new key: the next try is a different request (another name).
          update(row.key, {
            phase: "ready",
            nameError: "Another document in this department already has this name",
            idempotencyKey: crypto.randomUUID(),
          });
          return;
        }
        if (error instanceof ApiError && error.status === 422) {
          const errors = fieldErrors(error);
          update(row.key, {
            phase: "ready",
            nameError: errors.name ?? null,
            instructionsError: errors.ai_instructions ?? null,
            idempotencyKey: crypto.randomUUID(),
          });
          return;
        }
        if (error instanceof ApiError && error.code === "upload-not-found") {
          // Uploads expire after a day: Try again sends the file again.
          update(row.key, { phase: "failed", message: error.problem.title, canRetry: true });
          return;
        }
        update(row.key, { phase: "ready", message: formError(error) });
      });
  };

  const question = row?.phase === "question" ? row : null;
  const data = department;
  const head = (
    <HeadRow back={{ href: `/departments/${departmentId}/documents`, label: "Documents" }}>
      <Heading1>Upload a document</Heading1>
    </HeadRow>
  );
  if (!canUpload) {
    return (
      <>
        {head}
        <Notice>
          {data.status === "archived"
            ? "This department is archived. Restore it to add documents."
            : "Only people who can edit this department add documents."}
        </Notice>
      </>
    );
  }

  return (
    <>
      {head}
      <Section title={data.name}>
        {/* One document at a time: the dropzone until a file is chosen, then the file in its place. */}
        {row ? (
          <UploadRow
            row={row}
            onChange={(patch) => update(row.key, patch)}
            onAdd={() => create(row)}
            onRetry={() => retry(row)}
            onRemove={remove}
          />
        ) : (
          <Dropzone title="Drop a PDF or Word file" hint={limits.hint} accept=".pdf,.docx" onFile={addFile} />
        )}
      </Section>
      {question?.upload?.duplicate ? (
        <Dialog
          title="Already in this department"
          onClose={() => update(question.key, { phase: "cancelled", message: CANCELLED })}
          actions={
            <>
              <Button onClick={() => update(question.key, { phase: "ready", allowDuplicate: true })}>
                Upload anyway
              </Button>
              <TextButton onClick={() => update(question.key, { phase: "cancelled", message: CANCELLED })}>
                Cancel
              </TextButton>
            </>
          }
        >
          {`${question.file.name} is already in ${data.name} as ${question.upload.duplicate.document_name}${
            question.upload.duplicate.archived ? " (archived)" : ""
          }, version ${question.upload.duplicate.version_number}. Upload it anyway as a separate document?`}
        </Dialog>
      ) : null}
    </>
  );
}

function UploadRow({
  row,
  onChange,
  onAdd,
  onRetry,
  onRemove,
}: {
  row: Row;
  onChange: (patch: Partial<Row>) => void;
  onAdd: () => void;
  onRetry: () => void;
  onRemove: () => void;
}) {
  const editable = row.phase === "ready" || row.phase === "creating";
  return (
    <div className={styles.row}>
      <div className={styles.head}>
        <span className={styles.file}>{row.file.name}</span>
        <span className={styles.meta}>{formatBytes(row.file.size)}</span>
      </div>
      {row.phase === "uploading" ? (
        <div className={styles.transfer}>
          <progress
            className={styles.progress}
            value={row.progress}
            max={1}
            aria-label={`Uploading ${row.file.name}`}
          />
          <TextButton onClick={onRemove}>Cancel</TextButton>
        </div>
      ) : null}
      {editable ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onAdd();
          }}
          noValidate
        >
          <div className={styles.rows}>
            {row.message ? <Notice tone="warning">{row.message}</Notice> : null}
            <TextField
              label="Name"
              required
              maxLength={120}
              value={row.name}
              error={row.nameError ?? undefined}
              onChange={(event) => onChange({ name: event.target.value, nameError: null })}
            />
            <TextArea
              label="Instructions for the AI"
              hint="Optional. For example: two clients sign, and the firm countersigns."
              maxLength={1000}
              value={row.instructions}
              error={row.instructionsError ?? undefined}
              onChange={(event) => onChange({ instructions: event.target.value })}
            />
            <div className={styles.actions}>
              <Button type="submit" loading={row.phase === "creating"} loadingLabel="Adding…">
                Add document
              </Button>
              <TextButton onClick={onRemove}>Remove</TextButton>
            </div>
          </div>
        </form>
      ) : null}
      {row.phase === "failed" || row.phase === "cancelled" ? (
        <div className={styles.actions}>
          <span className={styles.message} role={row.phase === "failed" ? "alert" : "status"}>
            {row.message}
          </span>
          {row.phase === "failed" && row.canRetry ? (
            <TextButton onClick={onRetry}>Try again</TextButton>
          ) : null}
          <TextButton onClick={onRemove}>Remove</TextButton>
        </div>
      ) : null}
    </div>
  );
}
