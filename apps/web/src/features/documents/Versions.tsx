"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/shared/api/client";
import { formError } from "@/shared/api/errors";
import { Button, Dialog, Notice, StatusPill, TextButton } from "@/shared/ui";

import { documentKey, formatBytes, hasWorkingCopy, type DocumentDetail, type Version } from "./api";
import styles from "./document.module.css";
import { VERSION_STATUS } from "./status";

const dateTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

/** Every version, newest first (Phase 4 LLD §6.4): open, download the original, make current. */
export function Versions({
  document,
  viewing,
  onOpen,
  canEdit,
}: {
  document: DocumentDetail;
  viewing: string | null;
  onOpen: (versionId: string) => void;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState<Version | null>(null);
  const [redetecting, setRedetecting] = useState<Version | null>(null);
  const findAgain = useMutation({
    mutationFn: (version: Version) =>
      unwrap(
        api.POST("/api/v1/documents/{document_id}/versions/{version_id}/detection", {
          params: { path: { document_id: document.id, version_id: version.id } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: documentKey(document.id) });
      void queryClient.invalidateQueries({ queryKey: ["fields"] });
      setRedetecting(null);
    },
  });
  const makeCurrent = useMutation({
    mutationFn: (version: Version) =>
      unwrap(
        api.POST("/api/v1/documents/{document_id}/current-version", {
          params: { path: { document_id: document.id } },
          body: { version_id: version.id },
        }),
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(documentKey(document.id), updated);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      setConfirming(null);
    },
  });

  return (
    <>
      <ol className={styles.versions} aria-label="Versions">
        {document.versions.map((version) => {
          const status = VERSION_STATUS[version.status];
          const pages = version.page_count === null ? null : `${version.page_count} ${version.page_count === 1 ? "page" : "pages"}`;
          const fieldCount =
            version.status === "ready" && version.field_count !== null
              ? `${version.field_count} ${version.field_count === 1 ? "field" : "fields"}`
              : null;
          return (
            <li key={version.id} className={styles.version}>
              <div className={styles.versionHead}>
                <span className={styles.number}>{`v${version.number}${version.is_current ? " · Current" : ""}`}</span>
                <StatusPill status={status.pill} label={status.label} />
              </div>
              <span className={styles.detail}>
                {[version.filename, pages, fieldCount, formatBytes(version.bytes)].filter(Boolean).join(" · ")}
              </span>
              <span className={styles.detail}>{`${version.uploaded_by.name} · ${dateTime(version.created_at)}`}</span>
              <div className={styles.links}>
                {hasWorkingCopy(version.status) && version.id !== viewing ? (
                  <TextButton onClick={() => onOpen(version.id)}>Open</TextButton>
                ) : null}
                <a
                  className={styles.detail}
                  href={`/api/v1/documents/${document.id}/versions/${version.id}/original`}
                  download
                >
                  Download original
                </a>
                {canEdit && version.status === "ready" && !version.is_current ? (
                  <TextButton onClick={() => setConfirming(version)}>Make current</TextButton>
                ) : null}
                {canEdit && version.status === "ready" ? (
                  <TextButton onClick={() => setRedetecting(version)}>Find fields again</TextButton>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
      {confirming ? (
        <Dialog
          title={`Make version ${confirming.number} current?`}
          onClose={() => setConfirming(null)}
          actions={
            <>
              <Button loading={makeCurrent.isPending} loadingLabel="Saving…" onClick={() => makeCurrent.mutate(confirming)}>
                Make current
              </Button>
              <TextButton onClick={() => setConfirming(null)}>Cancel</TextButton>
            </>
          }
        >
          New sends will use it. A newer upload takes over again once it is ready.
          {makeCurrent.error ? <Notice tone="warning">{formError(makeCurrent.error)}</Notice> : null}
        </Dialog>
      ) : null}
      {redetecting ? (
        <Dialog
          title={`Find fields again for version ${redetecting.number}?`}
          onClose={() => setRedetecting(null)}
          actions={
            <>
              <Button loading={findAgain.isPending} loadingLabel="Starting…" onClick={() => findAgain.mutate(redetecting)}>
                Find fields again
              </Button>
              <TextButton onClick={() => setRedetecting(null)}>Cancel</TextButton>
            </>
          }
        >
          The fields found now will replace the current ones.
          {findAgain.error ? <Notice tone="warning">{formError(findAgain.error)}</Notice> : null}
        </Dialog>
      ) : null}
    </>
  );
}
