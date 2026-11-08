"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, formError } from "@/shared/api/errors";
import { Button, FieldAction, FieldGrid, Notice, TextField } from "@/shared/ui";

import { documentKey, type DocumentDetail, type Version } from "./api";

/**
 * Why a version is not ready, and what the person can do (Phase 4 LLD §6.4): wait while it
 * processes, enter the PDF's password (only in that state), try again after a passing failure, or
 * read which pages are scans.
 */
export function VersionState({
  document,
  version,
  canEdit,
}: {
  document: DocumentDetail;
  version: Version;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const path = { document_id: document.id, version_id: version.id };
  const onSaved = (updated: DocumentDetail) => queryClient.setQueryData(documentKey(document.id), updated);
  const retry = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/documents/{document_id}/versions/{version_id}/retry", { params: { path } })),
    onSuccess: onSaved,
  });
  const label = `Version ${version.number}`;

  if (version.status === "processing") {
    return <Notice title={label}>Processing… This page updates by itself.</Notice>;
  }
  if (version.status === "detecting") {
    return <Notice title={label}>Finding fields… This page updates by itself.</Notice>;
  }
  if (version.status === "needs_password") {
    return (
      <Notice title={label}>
        {canEdit ? <PasswordForm document={document} version={version} onSaved={onSaved} /> : version.problem?.message}
      </Notice>
    );
  }
  if (version.status === "failed" && version.problem) {
    return (
      <Notice
        tone="warning"
        title={label}
        action={
          canEdit && version.problem.can_retry ? (
            <Button variant="quiet" compact loading={retry.isPending} onClick={() => retry.mutate()}>
              Try again
            </Button>
          ) : undefined
        }
      >
        {`${version.problem.message}.`}
        {retry.error ? ` ${formError(retry.error)}` : ""}
      </Notice>
    );
  }
  if (version.status === "needs_ocr" && version.problem) {
    return (
      <Notice tone="warning" title={label}>
        {`${version.problem.message}. Upload a text-based PDF as a new version.`}
      </Notice>
    );
  }
  return null;
}

function PasswordForm({
  document,
  version,
  onSaved,
}: {
  document: DocumentDetail;
  version: Version;
  onSaved: (updated: DocumentDetail) => void;
}) {
  const [password, setPassword] = useState("");
  const unlock = useMutation({
    mutationFn: (value: string) =>
      unwrap(
        api.POST("/api/v1/documents/{document_id}/versions/{version_id}/unlock", {
          params: { path: { document_id: document.id, version_id: version.id } },
          body: { password: value },
        }),
      ),
    onSuccess: (updated) => {
      setPassword("");
      onSaved(updated);
    },
  });
  const error = unlock.error;
  const message =
    error instanceof ApiError && error.code === "wrong-password"
      ? "Wrong password"
      : error instanceof ApiError && error.code === "rate-limited"
        ? `Too many tries. Try again in ${Math.ceil((error.retryAfterSeconds ?? 60) / 60)} min`
        : error
          ? formError(error) ?? undefined
          : undefined;
  return (
    <form
      onSubmit={(event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (password) unlock.mutate(password);
      }}
      noValidate
    >
      <FieldGrid>
        <TextField
          label="This PDF needs a password to open"
          type="password"
          autoComplete="off"
          value={password}
          error={message}
          onChange={(event) => setPassword(event.target.value)}
        />
        <FieldAction>
          <Button type="submit" variant="quiet" disabled={!password} loading={unlock.isPending} loadingLabel="Opening…">
            Open
          </Button>
        </FieldAction>
      </FieldGrid>
    </form>
  );
}
