"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import { Button, TextArea, TextButton } from "@/shared/ui";

import { documentKey, formatBytes, uploadFile, type Upload } from "./api";
import styles from "./document.module.css";
import { useDocumentLimits } from "./limits";

/** A file on its way up, before it is a version. */
export type Uploading = { name: string; progress: number };

/** A file that has arrived, waiting for the person's notes before it becomes a version. */
export type Pending = { name: string; upload: Upload; key: string };

type State = { step: "idle" } | ({ step: "uploading" } & Uploading) | ({ step: "ready" | "adding" } & Pending);

/**
 * Add a new version (Phase 4 LLD §6.4): the file uploads as soon as it is picked and shows its
 * progress; then, before it is added, the person may give the AI instructions for this version
 * (what changed, who signs), as at the first upload. A file identical to any version in the
 * department is never a version (§2.3): the person is told where it already is.
 */
export function useNewVersion(departmentId: string, documentId: string) {
  const queryClient = useQueryClient();
  const limits = useDocumentLimits();
  const [state, setState] = useState<State>({ step: "idle" });
  const [problem, setProblem] = useState<string | null>(null);
  const [instructionsError, setInstructionsError] = useState<string | null>(null);

  const start = (file: File) => {
    setProblem(null);
    if (limits.maxBytes !== undefined && file.size > limits.maxBytes) {
      setProblem(`Upload a file of ${formatBytes(limits.maxBytes)} or less`);
      return;
    }
    setState({ step: "uploading", name: file.name, progress: 0 });
    uploadFile(departmentId, file, (progress) =>
      setState((current) => (current.step === "uploading" ? { ...current, progress } : current)),
    )
      .then((upload) => {
        if (upload.duplicate) {
          const where = upload.duplicate;
          setState({ step: "idle" });
          setProblem(
            `This file is already here as ${where.document_name}${where.archived ? " (archived)" : ""}, version ${where.version_number}. It can only be added as a separate document.`,
          );
          return;
        }
        setState({ step: "ready", name: file.name, upload, key: crypto.randomUUID() });
      })
      .catch((error: unknown) => {
        setState({ step: "idle" });
        setProblem(error instanceof ApiError ? error.problem.title : formError(error));
      });
  };

  const add = (instructions: string) => {
    if (state.step !== "ready") return;
    const pending: Pending = { name: state.name, upload: state.upload, key: state.key };
    setState({ step: "adding", ...pending });
    setInstructionsError(null);
    unwrap(
      api.POST("/api/v1/documents/{document_id}/versions", {
        params: { path: { document_id: documentId } },
        headers: { "Idempotency-Key": pending.key },
        body: { upload_id: pending.upload.id, ai_instructions: instructions },
      }),
    )
      .then((updated) => {
        queryClient.setQueryData(documentKey(documentId), updated);
        void queryClient.invalidateQueries({ queryKey: ["documents"] });
        setState({ step: "idle" });
      })
      .catch((error: unknown) => {
        // The next try is a different request: a new key.
        setState({ step: "ready", ...pending, key: crypto.randomUUID() });
        if (error instanceof ApiError && error.status === 422) {
          setInstructionsError(fieldErrors(error).ai_instructions ?? null);
          return;
        }
        setProblem(error instanceof ApiError ? error.problem.title : formError(error));
      });
  };

  const cancel = () => setState({ step: "idle" });

  return {
    start,
    add,
    cancel,
    problem,
    instructionsError,
    uploading: state.step === "uploading" ? { name: state.name, progress: state.progress } : null,
    pending: state.step === "ready" || state.step === "adding" ? { name: state.name, upload: state.upload, key: state.key } : null,
    adding: state.step === "adding",
    busy: state.step !== "idle",
  };
}

/** The arrived file's name, the instructions for the AI, and Add version (Phase 4 LLD §6.4). */
export function NewVersionForm({
  pending,
  adding,
  error,
  onAdd,
  onCancel,
}: {
  pending: Pending;
  adding: boolean;
  error: string | null;
  onAdd: (instructions: string) => void;
  onCancel: () => void;
}) {
  const [instructions, setInstructions] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onAdd(instructions);
  };
  return (
    <form onSubmit={submit} noValidate className={styles.newVersion} aria-label="New version">
      <span className={styles.detail}>{pending.name}</span>
      <TextArea
        label="Instructions for the AI"
        hint="Optional. For example: what changed, or two clients sign and the firm countersigns."
        maxLength={1000}
        value={instructions}
        error={error ?? undefined}
        onChange={(event) => setInstructions(event.target.value)}
      />
      <div className={styles.links}>
        <Button type="submit" loading={adding} loadingLabel="Adding…">
          Add version
        </Button>
        <TextButton onClick={onCancel}>Cancel</TextButton>
      </div>
    </form>
  );
}
