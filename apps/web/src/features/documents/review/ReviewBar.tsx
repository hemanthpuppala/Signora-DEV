"use client";

import { useState } from "react";

import { ApiError, formError } from "@/shared/api/errors";
import { ActionBar, Button, Dialog, HeadAction, Notice, TextButton } from "@/shared/ui";

import type { Version } from "../api";
import type { Review } from "./useReview";
import styles from "./review.module.css";
import type { ReviewWarning } from "./ThingsToCheck";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * The review's action bar (Phase 6 §7.1): where the version stands on the left, what can be done
 * on the right. In review: Approve (it waits while changes are unsaved: what is approved is what
 * is saved). With changes: Undo, Discard, Save; for an approved version Save makes the next one,
 * and the bar says so. Read-only members see the state only.
 */
export function ReviewActionBar({
  review,
  version,
  nextNumber,
  warnings,
  canEdit,
  editInPanel = false,
}: {
  review: Review;
  version: Version;
  nextNumber: number;
  warnings: readonly ReviewWarning[];
  canEdit: boolean;
  /** "Edit fields" is in the panel, by what it edits (a narrow screen): not here, alone on a line
   * over the document. */
  editInPanel?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const { changes, editing, approved, inReview } = review;
  // The version and its state are under the document's title (DocumentPage); here, what changes.
  const facts = [
    inReview && warnings.length > 0 ? plural(warnings.length, "thing to check", "things to check") : null,
    changes > 0 ? plural(changes, "unsaved change", "unsaved changes") : null,
    approved && editing ? `Saving makes version ${nextNumber}; version ${version.number} stays as it is` : null,
  ].filter(Boolean);

  const actions =
    !canEdit ? null : editing && changes > 0 ? (
      <>
        <HeadAction icon="undo" label="Undo" disabled={!review.canUndo} onClick={review.undo} />
        <HeadAction icon="discard" label="Discard" onClick={review.discard} />
        <HeadAction
          icon="save"
          label={review.saving ? "Saving…" : approved ? `Save as version ${nextNumber}` : "Save"}
          variant="primary"
          disabled={review.saving}
          onClick={review.save}
        />
      </>
    ) : review.canApprove ? (
      <HeadAction icon="check" label="Approve version" variant="primary" onClick={() => setConfirming(true)} />
    ) : approved && !editing && !editInPanel ? (
      <HeadAction icon="edit" label="Edit fields" onClick={review.startEditing} />
    ) : approved && editing ? (
      <HeadAction icon="close" label="Stop editing" onClick={review.stopEditing} />
    ) : null;

  return (
    <>
      <ActionBar label="Review" actions={actions}>
        {facts.length > 0 ? facts.map((fact, index) => <span key={index}>{fact}</span>) : null}
      </ActionBar>
      {confirming ? (
        <ApproveDialog
          review={review}
          number={version.number}
          warnings={warnings}
          onClose={() => {
            setConfirming(false);
            review.approve.reset();
          }}
        />
      ) : null}
    </>
  );
}

/** What went wrong with a save: someone else saved (Reload), or which fields to fix (each opens it). */
export function SaveProblem({ review, onShow }: { review: Review; onShow: (fieldId: string) => void }) {
  const { problem } = review;
  if (!problem) return null;
  return (
    <Notice
      tone="warning"
      title={problem.message}
      action={
        problem.stale ? (
          <Button variant="quiet" compact onClick={() => void review.reload()}>
            Reload
          </Button>
        ) : undefined
      }
    >
      {problem.stale ? (
        "Reloading shows their changes; yours will be lost."
      ) : problem.items.length > 0 ? (
        <ul className={styles.problems}>
          {problem.items.map((item, index) => (
            <li key={index}>
              {item.fieldId ? <TextButton onClick={() => onShow(item.fieldId ?? "")}>{item.message}</TextButton> : item.message}
            </li>
          ))}
        </ul>
      ) : null}
    </Notice>
  );
}

function ApproveDialog({
  review,
  number,
  warnings,
  onClose,
}: {
  review: Review;
  number: number;
  warnings: readonly ReviewWarning[];
  onClose: () => void;
}) {
  const { approve } = review;
  const stale = approve.error instanceof ApiError && ["fields-changed", "warnings-changed"].includes(approve.error.code);
  return (
    <Dialog
      title={`Approve version ${number}?`}
      onClose={onClose}
      actions={
        <>
          {stale ? (
            <Button
              variant="quiet"
              onClick={() => {
                onClose();
                void review.reload();
              }}
            >
              Reload
            </Button>
          ) : (
            <Button loading={approve.isPending} loadingLabel="Approving…" onClick={() => approve.mutate(undefined, { onSuccess: onClose })}>
              {warnings.length > 0 ? "Approve anyway" : "Approve"}
            </Button>
          )}
          <TextButton onClick={onClose}>Cancel</TextButton>
        </>
      }
    >
      <p className={styles.dialogText}>
        Its fields freeze and it can be sent. It becomes the current version unless a newer one is approved.
      </p>
      {warnings.length > 0 ? (
        <ul className={styles.problems} aria-label="Things to check">
          {warnings.map((warning, index) => (
            <li key={index}>{warning.message}</li>
          ))}
        </ul>
      ) : null}
      {approve.error ? <Notice tone="warning">{formError(approve.error)}</Notice> : null}
    </Dialog>
  );
}
