"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import {
  Button,
  Dialog,
  Dropzone,
  HeadRow,
  Heading1,
  LinkButton,
  Notice,
  Section,
  StatusPill,
  TextArea,
  TextButton,
  TextField,
} from "@/shared/ui";
import {
  clearHandOff,
  documentsKey,
  formatBytes,
  handedOffFiles,
  uploadFile,
  useDocument,
  type DepartmentRef,
  type Upload,
} from "./api";
import { useDocumentLimits } from "./limits";
import { VERSION_STATUS } from "./status";
import styles from "./upload.module.css";

type Phase = "uploading" | "question" | "ready" | "creating" | "added" | "failed" | "cancelled";

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
  nameError: string | null;
  instructionsError: string | null;
  documentId: string | null;
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
    nameError: null,
    instructionsError: null,
    documentId: null,
  };
}

function uploadProblem(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "payload-too-large") return "Upload a file of 50 MB or less";
    return error.problem.title;
  }
  return formError(error) ?? "The upload didn't finish. Try again";
}

/**
 * Screen 11 (Phase 4 LLD §6.2): one file per upload, and the next file may be dropped while
 * earlier ones are still uploading or processing. Each row has its own progress, name,
 * instructions for the AI, duplicate question and, once added, its live processing status.
 */
export function UploadPage({ department }: { department: DepartmentRef }) {
  const departmentId = department.id;
  const queryClient = useQueryClient();
  const limits = useDocumentLimits();
  // Files handed over from the department or new-department page start as rows at once.
  const [rows, setRows] = useState<Row[]>(() => handedOffFiles(departmentId).map((file) => newRow(file, null)));

  const update = useCallback((key: string, patch: Partial<Row>) => {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  }, []);

  // Starts the transfer; its progress and result arrive later, as events.
  const transfer = useCallback(
    (key: string, file: File) => {
      uploadFile(departmentId, file, (progress) => update(key, { progress }))
        .then((upload) =>
          update(key, {
            upload,
            name: upload.suggested_name,
            phase: upload.duplicate ? "question" : "ready",
          }),
        )
        .catch((error: unknown) => update(key, { phase: "failed", message: uploadProblem(error) }));
    },
    [departmentId, update],
  );

  // Transfers for the handed-over rows, once each (effects may run twice in development).
  const started = useRef(new Set<string>());
  useEffect(() => {
    clearHandOff(departmentId);
    for (const row of rows) {
      if (row.phase === "uploading" && !started.current.has(row.key)) {
        started.current.add(row.key);
        transfer(row.key, row.file);
      }
    }
  }, [departmentId, rows, transfer]);

  const addFile = (file: File) => {
    const tooLarge = limits.maxBytes !== undefined && file.size > limits.maxBytes;
    const row = newRow(file, tooLarge ? `Upload a file of ${formatBytes(limits.maxBytes ?? 0)} or less` : null);
    setRows((current) => [...current, row]); // the effect above starts its transfer
  };

  // A new key makes the effect above start a fresh transfer for the same file.
  const retry = (row: Row) =>
    update(row.key, { key: crypto.randomUUID(), phase: "uploading", progress: 0, message: null });

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
        update(row.key, { phase: "added", documentId: document.id });
        void queryClient.invalidateQueries({ queryKey: documentsKey(departmentId) });
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
          update(row.key, { phase: "failed", message: error.problem.title });
          return;
        }
        update(row.key, { phase: "ready", message: formError(error) });
      });
  };

  const question = rows.find((row) => row.phase === "question");
  const data = department;
  const back = `/departments/${departmentId}`;
  if (data.status === "archived" || data.access !== "edit") {
    return (
      <Notice action={<LinkButton href={back} variant="quiet">Back</LinkButton>}>
        {data.status === "archived"
          ? "This department is archived. Restore it to add documents."
          : "Only people who can edit this department add documents."}
      </Notice>
    );
  }

  return (
    <>
      <HeadRow actions={<LinkButton href={back} variant="quiet">Back</LinkButton>}>
        <Heading1>Upload documents</Heading1>
      </HeadRow>
      <Section title={data.name}>
        <Dropzone title="Drop a PDF or Word file" hint={limits.hint} accept=".pdf,.docx" onFile={addFile} />
        {rows.length > 0 ? (
          <ol className={styles.rows} aria-label="Uploads">
            {rows.map((row) => (
              <UploadRow
                key={row.key}
                row={row}
                departmentId={departmentId}
                onChange={(patch) => update(row.key, patch)}
                onAdd={() => create(row)}
                onRetry={() => retry(row)}
                onRemove={() => setRows((current) => current.filter((other) => other.key !== row.key))}
              />
            ))}
          </ol>
        ) : null}
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
  departmentId,
  onChange,
  onAdd,
  onRetry,
  onRemove,
}: {
  row: Row;
  departmentId: string;
  onChange: (patch: Partial<Row>) => void;
  onAdd: () => void;
  onRetry: () => void;
  onRemove: () => void;
}) {
  const editable = row.phase === "ready" || row.phase === "creating";
  return (
    <li className={styles.row}>
      <div className={styles.head}>
        <span className={styles.file}>{row.file.name}</span>
        <span className={styles.meta}>{formatBytes(row.file.size)}</span>
      </div>
      {row.phase === "uploading" ? (
        <progress
          className={styles.progress}
          value={row.progress}
          max={1}
          aria-label={`Uploading ${row.file.name}`}
        />
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
      {row.phase === "added" && row.documentId ? (
        <AddedStatus departmentId={departmentId} documentId={row.documentId} />
      ) : null}
      {row.phase === "failed" || row.phase === "cancelled" ? (
        <div className={styles.actions}>
          <span className={styles.message} role={row.phase === "failed" ? "alert" : "status"}>
            {row.message}
          </span>
          {row.phase === "failed" && row.upload === null && row.message !== null && !row.message.startsWith("Upload a") ? (
            <TextButton onClick={onRetry}>Try again</TextButton>
          ) : null}
          <TextButton onClick={onRemove}>Remove</TextButton>
        </div>
      ) : null}
    </li>
  );
}

/** After "Add document": the version's live state, until it is ready or needs something. */
function AddedStatus({ departmentId, documentId }: { departmentId: string; documentId: string }) {
  const document = useDocument(documentId);
  const version = document.data?.versions[0];
  if (!version) return null;
  const status = VERSION_STATUS[version.status];
  return (
    <div className={styles.actions}>
      <StatusPill status={status.pill} label={status.label} />
      {version.problem ? <span className={styles.message}>{version.problem.message}</span> : null}
      <Link href={`/departments/${departmentId}/documents/${documentId}`}>Open</Link>
    </div>
  );
}
