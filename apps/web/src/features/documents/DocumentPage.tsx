"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import {
  Button,
  Checkbox,
  ClampedText,
  Eyebrow,
  HeadRow,
  Heading1,
  LinkButton,
  Notice,
  PdfViewer,
  RowActions,
  Section,
  SmallText,
  TextArea,
  TextButton,
  TextField,
} from "@/shared/ui";

import { documentKey, hasWorkingCopy, useDocument, type DocumentDetail } from "./api";
import styles from "./document.module.css";
import { NewVersion } from "./NewVersion";
import { Versions } from "./Versions";
import { VersionState } from "./VersionState";

type Patch = { name?: string; description?: string; require_email_code?: boolean };

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
  const { patch, archive } = useDocumentAction(documentId);
  const [editing, setEditing] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);

  if (document.isError) {
    const missing = document.error instanceof ApiError && document.error.status === 404;
    return <Notice tone="warning">{missing ? "This document doesn't exist." : formError(document.error)}</Notice>;
  }
  const data = document.data;
  if (!data) return null;

  const archived = data.archived_at !== null;
  const canEdit = data.access === "edit" && !archived;
  const newest = data.versions[0];
  const shownId = viewing ?? data.current_version?.id ?? null;
  const shown = data.versions.find((version) => version.id === shownId && hasWorkingCopy(version.status));
  const back = `/departments/${departmentId}`;

  return (
    <>
      <HeadRow
        actions={
          <>
            {canEdit && !editing ? (
              <Button variant="quiet" onClick={() => setEditing(true)}>
                Edit
              </Button>
            ) : null}
            <LinkButton href={back} variant="quiet">
              Back
            </LinkButton>
          </>
        }
      >
        <Eyebrow>Document</Eyebrow>
        <Heading1>{data.name}</Heading1>
        {data.description && !editing ? <ClampedText>{data.description}</ClampedText> : null}
      </HeadRow>
      {editing ? <About document={data} onDone={() => setEditing(false)} /> : null}
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
      <div className={styles.layout}>
        <div className={styles.main}>
          {newest && newest.status !== "ready" ? (
            <VersionState document={data} version={newest} canEdit={canEdit} />
          ) : null}
          {shown ? (
            <>
              <div className={styles.caption}>
                <span>{`Version ${shown.number}${shown.is_current ? " · Current" : ""}`}</span>
                {shown.id !== data.current_version?.id && data.current_version ? (
                  <TextButton onClick={() => setViewing(null)}>Back to the current version</TextButton>
                ) : null}
              </div>
              <PdfViewer
                url={`/api/v1/documents/${data.id}/versions/${shown.id}/pdf`}
                pages={shown.pages}
                label={`${data.name}, version ${shown.number}`}
              />
            </>
          ) : null}
        </div>
        <div className={styles.side}>
          <Section title="Signing">
            <Checkbox
              checked={data.require_email_code}
              disabled={!canEdit || patch.isPending}
              onChange={(event) => patch.mutate({ require_email_code: event.target.checked })}
            >
              Require email code
            </Checkbox>
            <SmallText>Clients enter a code sent to their email before they can sign. Each send keeps this setting.</SmallText>
          </Section>
          <Section title="Versions">
            <Versions document={data} viewing={shownId} onOpen={setViewing} canEdit={canEdit} />
          </Section>
          {canEdit ? (
            <Section title="New version">
              <NewVersion document={data} />
            </Section>
          ) : null}
          {canEdit ? (
            <Section title="Archive">
              {confirmArchive ? (
                <RowActions label="Confirm archiving">
                  <Button variant="destructive" loading={archive.isPending} onClick={() => archive.mutate("archive")}>
                    Confirm archive
                  </Button>
                  <TextButton onClick={() => setConfirmArchive(false)}>Cancel</TextButton>
                </RowActions>
              ) : (
                <div>
                  <Button variant="destructive" onClick={() => setConfirmArchive(true)}>
                    Archive document
                  </Button>
                </div>
              )}
            </Section>
          ) : null}
        </div>
      </div>
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
