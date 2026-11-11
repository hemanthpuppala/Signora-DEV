"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/shared/api/client";
import { formError } from "@/shared/api/errors";
import { Button, Dialog, IconButton, Notice, StatusPill, TextButton, Tooltip } from "@/shared/ui";

import { documentKey, hasWorkingCopy, type DocumentDetail, type Version } from "./api";
import styles from "./document.module.css";
import { VersionLabel } from "./VersionLabel";
import { VERSION_STATUS } from "./status";

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
            (version.status === "ready" || version.status === "approved") && version.field_count !== null
              ? `${version.field_count} ${version.field_count === 1 ? "field" : "fields"}`
              : null;
          return (
            <li key={version.id} className={`${styles.version}${version.id === viewing ? ` ${styles.viewing}` : ""}`}>
              <div className={styles.versionHead}>
                <span className={styles.number}>
                  <VersionLabel number={version.number} current={version.is_current} />
                </span>
                {version.approved ? (
                  <Tooltip label={`Approved by ${version.approved.by.name} on ${new Date(version.approved.at).toLocaleDateString()}`}>
                    <StatusPill status={status.pill} label={status.label} />
                  </Tooltip>
                ) : (
                  <StatusPill status={status.pill} label={status.label} />
                )}
              </div>
              {/* What the AI called this version, once its fields are found; the file name until then. */}
              <Tooltip
                label={version.name ? `${version.name} (${version.filename})` : version.filename}
                className={styles.filenameTip}
              >
                <span className={styles.filename}>{version.name ?? version.filename}</span>
              </Tooltip>
              <span className={styles.detail}>
                {[version.derived_from ? `from version ${version.derived_from}` : null, pages, fieldCount]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {/* One line: download at the start, the words in the middle, make current (a star) at the end. */}
              <div className={styles.versionActions}>
                <IconButton
                  icon="download"
                  label="Download original"
                  href={`/api/v1/documents/${document.id}/versions/${version.id}/original`}
                  download
                />
                {hasWorkingCopy(version.status) && version.id !== viewing ? (
                  <button type="button" className={styles.action} onClick={() => onOpen(version.id)}>
                    Open
                  </button>
                ) : null}
                {canEdit && version.status === "ready" ? (
                  <button type="button" className={styles.action} onClick={() => setRedetecting(version)}>
                    Find fields again
                  </button>
                ) : null}
                {canEdit && version.status === "approved" && !version.is_current ? (
                  <span className={styles.actionEnd}>
                    <IconButton icon="star" label="Make current" onClick={() => setConfirming(version)} />
                  </span>
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
          New sends will use it. A newer version takes over again once it is approved.
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
