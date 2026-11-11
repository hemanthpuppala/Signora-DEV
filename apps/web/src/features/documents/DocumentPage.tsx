"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import {
  Button,
  ClampedText,
  Dialog,
  HeadAction,
  HeadRow,
  Heading1,
  Notice,
  Section,
  TextArea,
  TextButton,
  TextField,
} from "@/shared/ui";

import { documentKey, hasWorkingCopy, useDocument, type DocumentDetail } from "./api";
import styles from "./document.module.css";
import { useVersionFields } from "./fields";
import { VersionLabel } from "./VersionLabel";
import { VersionProgress } from "./VersionProgress";
import { NewVersionForm, useNewVersion } from "./NewVersion";
import { ReviewLayout } from "./review/ReviewLayout";
import { Versions } from "./Versions";
import { VersionState } from "./VersionState";

type Patch = { name?: string; description?: string };

function useDocumentAction(id: string) {
  const queryClient = useQueryClient();
  const save = (updated: DocumentDetail) => {
    queryClient.setQueryData(documentKey(id), updated);
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  };
  const patch = useMutation({
    mutationFn: (body: Patch) =>
      unwrap(api.PATCH("/api/v1/documents/{document_id}", { params: { path: { document_id: id } }, body })),
    onSuccess: save,
  });
  const archive = useMutation({
    mutationFn: (to: "archive" | "restore") =>
      unwrap(
        to === "archive"
          ? api.POST("/api/v1/documents/{document_id}/archive", { params: { path: { document_id: id } } })
          : api.POST("/api/v1/documents/{document_id}/restore", { params: { path: { document_id: id } } }),
      ),
    onSuccess: save,
  });
  return { patch, archive };
}

/**
 * One document (Phase 4 LLD §6.4): the viewer, large, with the details beside it. The newest
 * version's state shows above the viewer until it is ready. People without edit access see the
 * viewer, the versions and downloads only.
 */
export function DocumentPage({ departmentId, documentId }: { departmentId: string; documentId: string }) {
  const document = useDocument(documentId);
  const { archive } = useDocumentAction(documentId);
  const [editing, setEditing] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const newVersion = useNewVersion(departmentId, documentId);
  const fileInput = useRef<HTMLInputElement>(null);
  // The version shown: the one opened, else the current one, else (while the first version's
  // fields are found) the newest one that can be shown (Phase 5 §6.3).
  const versions = document.data?.versions ?? [];
  const shownId =
    viewing ?? document.data?.current_version?.id ?? versions.find((version) => hasWorkingCopy(version.status))?.id ?? null;
  const shown = versions.find((version) => version.id === shownId && hasWorkingCopy(version.status));
  const fields = useVersionFields(documentId, shown);

  if (document.isError) {
    const missing = document.error instanceof ApiError && document.error.status === 404;
    return <Notice tone="warning">{missing ? "This document doesn't exist." : formError(document.error)}</Notice>;
  }
  const data = document.data;
  if (!data) return null;

  const archived = data.archived_at !== null;
  const canEdit = data.access === "edit" && !archived;
  const newest = data.versions[0];
  const back = `/departments/${departmentId}/documents`;
  const progress = (
    <>
      {newVersion.problem ? <Notice tone="warning">{newVersion.problem}</Notice> : null}
      <VersionProgress uploading={newVersion.uploading} version={newest} />
      {newVersion.pending ? (
        <NewVersionForm
          pending={newVersion.pending}
          adding={newVersion.adding}
          error={newVersion.instructionsError}
          onAdd={newVersion.add}
          onCancel={newVersion.cancel}
        />
      ) : null}
      {newest && newest.status !== "ready" && newest.status !== "approved" ? (
        <VersionState document={data} version={newest} canEdit={canEdit} />
      ) : null}
    </>
  );

  return (
    <>
      {/* The way back and the document's actions share one line, so the title block is shorter. */}
      <HeadRow
        back={{ href: back, label: "Documents" }}
        backActions={
          canEdit ? (
            <div className={styles.headActions} role="group" aria-label="Document actions">
              <HeadAction
                icon="upload"
                label="New version"
                disabled={newVersion.busy}
                onClick={() => fileInput.current?.click()}
              />
              <input
                ref={fileInput}
                type="file"
                accept=".pdf,.docx"
                hidden
                aria-label="New version file"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = ""; // the same file can be picked again
                  if (file) newVersion.start(file);
                }}
              />
              {!editing ? <HeadAction icon="edit" label="Edit" onClick={() => setEditing(true)} /> : null}
              <HeadAction
                icon="archive"
                label="Archive document"
                variant="destructive"
                onClick={() => setConfirmArchive(true)}
              />
            </div>
          ) : undefined
        }
      >
        <div className={styles.titleLine}>
          <Heading1>{data.name}</Heading1>
          {shown ? (
            <span className={styles.number}>
              <VersionLabel number={shown.number} current={shown.is_current} />
            </span>
          ) : null}
        </div>
        {data.description && !editing ? <ClampedText>{data.description}</ClampedText> : null}
      </HeadRow>
      {editing ? <About document={data} onDone={() => setEditing(false)} /> : null}
      {confirmArchive && canEdit ? (
        <Dialog
          title="Archive this document?"
          onClose={() => setConfirmArchive(false)}
          actions={
            <>
              <Button variant="destructive" loading={archive.isPending} onClick={() => archive.mutate("archive")}>
                Confirm archive
              </Button>
              <TextButton onClick={() => setConfirmArchive(false)}>Cancel</TextButton>
            </>
          }
        >
          {"It can't get new versions or be sent. It can be restored later."}
          {archive.error ? <Notice tone="warning">{formError(archive.error)}</Notice> : null}
        </Dialog>
      ) : null}
      {archived ? (
        <Notice
          title="Archived"
          action={
            data.access === "edit" ? (
              <Button variant="quiet" compact loading={archive.isPending} onClick={() => archive.mutate("restore")}>
                Restore
              </Button>
            ) : undefined
          }
        >
          {archive.error ? formError(archive.error) : "This document can't get new versions or be sent."}
        </Notice>
      ) : null}
      {shown ? (
        <ReviewLayout
          key={shown.id}
          document={data}
          version={shown}
          view={fields.data}
          canEdit={canEdit}
          top={progress}
          onOpen={setViewing}
        />
      ) : (
        <div className={styles.layout}>
          <div className={styles.main}>{progress}</div>
          <div className={styles.side}>
            <Section title="Versions">
              <Versions document={data} viewing={shownId} onOpen={setViewing} canEdit={canEdit} />
            </Section>
          </div>
        </div>
      )}
    </>
  );
}

/** Name and description, edited by a person; the AI never replaces them afterwards. */
function About({ document, onDone }: { document: DocumentDetail; onDone: () => void }) {
  const { patch } = useDocumentAction(document.id);
  const [name, setName] = useState(document.name);
  const [description, setDescription] = useState(document.description);
  const error = patch.error;
  const nameTaken = error instanceof ApiError && error.code === "document-name-taken";
  const errors = fieldErrors(error);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    patch.mutate(
      {
        ...(name !== document.name ? { name } : {}),
        ...(description !== document.description ? { description } : {}),
      },
      { onSuccess: onDone },
    );
  };
  return (
    <form onSubmit={submit} noValidate>
      <Section title="About">
        {error && !nameTaken && !Object.keys(errors).length ? <Notice tone="warning">{formError(error)}</Notice> : null}
        <TextField
          label="Name"
          required
          maxLength={120}
          value={name}
          error={nameTaken ? "Another document in this department already has this name" : errors.name}
          onChange={(event) => setName(event.target.value)}
        />
        <TextArea
          label="Description"
          maxLength={500}
          value={description}
          error={errors.description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <div className={styles.links}>
          <Button type="submit" variant="quiet" loading={patch.isPending} loadingLabel="Saving…">
            Save
          </Button>
          <TextButton onClick={onDone}>Cancel</TextButton>
        </div>
      </Section>
    </form>
  );
}
