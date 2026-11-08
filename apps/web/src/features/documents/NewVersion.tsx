"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, formError } from "@/shared/api/errors";
import { Button, Dropzone, Notice, TextArea, TextButton } from "@/shared/ui";

import { documentKey, formatBytes, uploadFile, type DocumentDetail, type Upload } from "./api";
import styles from "./document.module.css";
import { useDocumentLimits } from "./limits";

type State =
  | { step: "idle" }
  | { step: "uploading"; file: File; progress: number }
  | { step: "ready"; file: File; upload: Upload; key: string }
  | { step: "adding"; file: File; upload: Upload; key: string };

/**
 * Upload a new version (Phase 4 LLD §6.4). A file identical to any version in the department is
 * never a version (§2.3): the person is told where it already is.
 */
export function NewVersion({ document }: { document: DocumentDetail }) {
  const queryClient = useQueryClient();
  const limits = useDocumentLimits();
  const [state, setState] = useState<State>({ step: "idle" });
  const [instructions, setInstructions] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const start = (file: File) => {
    setProblem(null);
    if (limits.maxBytes !== undefined && file.size > limits.maxBytes) {
      setProblem(`Upload a file of ${formatBytes(limits.maxBytes)} or less`);
      return;
    }
    setState({ step: "uploading", file, progress: 0 });
    uploadFile(document.department_id, file, (progress) =>
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
        setState({ step: "ready", file, upload, key: crypto.randomUUID() });
      })
      .catch((error: unknown) => {
        setState({ step: "idle" });
        setProblem(error instanceof ApiError ? error.problem.title : formError(error));
      });
  };

  const add = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (state.step !== "ready") return;
    setState({ ...state, step: "adding" });
    unwrap(
      api.POST("/api/v1/documents/{document_id}/versions", {
        params: { path: { document_id: document.id } },
        headers: { "Idempotency-Key": state.key },
        body: { upload_id: state.upload.id, ai_instructions: instructions },
      }),
    )
      .then((updated) => {
        queryClient.setQueryData(documentKey(document.id), updated);
        void queryClient.invalidateQueries({ queryKey: ["documents"] });
        setState({ step: "idle" });
        setInstructions("");
      })
      .catch((error: unknown) => {
        setState({ ...state, step: "ready" });
        setProblem(formError(error));
      });
  };

  return (
    <div className={styles.stack}>
      {problem ? <Notice tone="warning">{problem}</Notice> : null}
      {state.step === "idle" ? (
        <Dropzone title="Drop the new version" hint={limits.hint} accept=".pdf,.docx" onFile={start} />
      ) : null}
      {state.step === "uploading" ? (
        <progress value={state.progress} max={1} aria-label={`Uploading ${state.file.name}`} />
      ) : null}
      {state.step === "ready" || state.step === "adding" ? (
        <form onSubmit={add} noValidate className={styles.stack}>
          <span className={styles.detail}>{state.file.name}</span>
          <TextArea
            label="Instructions for the AI"
            hint="Optional. What changed, or what to look for."
            maxLength={1000}
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
          />
          <div className={styles.links}>
            <Button type="submit" loading={state.step === "adding"} loadingLabel="Adding…">
              Add version
            </Button>
            <TextButton onClick={() => setState({ step: "idle" })}>Cancel</TextButton>
          </div>
        </form>
      ) : null}
    </div>
  );
}
