"use client";

import { useState } from "react";

import { ApiError, formError } from "@/shared/api/errors";
import { ActionBar, Button, Dialog, Notice, TextButton } from "@/shared/ui";

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
}: {
  review: Review;
  version: Version;
  nextNumber: number;
  warnings: readonly ReviewWarning[];
  canEdit: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const { changes, editing, approved, inReview } = review;
  const state = approved
    ? version.approved
      ? `Approved by ${version.approved.by.name} on ${new Date(version.approved.at).toLocaleDateString()}`
      : "Approved"
    : inReview
      ? "Needs approval"
      : null;
  const facts = [
    `Version ${version.number}`,
    state,
    inReview && warnings.length > 0 ? plural(warnings.length, "thing to check", "things to check") : null,
    changes > 0 ? plural(changes, "unsaved change", "unsaved changes") : null,
    approved && editing ? `Saving makes version ${nextNumber}; version ${version.number} stays as it is` : null,
  ].filter(Boolean);

  const actions =
    !canEdit ? null : editing && changes > 0 ? (
      <>
        <TextButton disabled={!review.canUndo} onClick={review.undo}>
          Undo
        </TextButton>
        <TextButton onClick={review.discard}>Discard</TextButton>
        <Button compact loading={review.saving} loadingLabel="Saving…" onClick={review.save}>
          {approved ? `Save as version ${nextNumber}` : "Save"}
        </Button>
      </>
    ) : review.canApprove ? (
      <Button compact onClick={() => setConfirming(true)}>
        Approve version
      </Button>
    ) : approved && !editing ? (
      <Button variant="quiet" compact onClick={review.startEditing}>
        Edit fields
      </Button>
    ) : approved && editing ? (
      <TextButton onClick={review.stopEditing}>Stop editing</TextButton>
    ) : null;

  return (
    <>
      <ActionBar label="Review" actions={actions}>
        {facts.map((fact, index) => (
          <span key={index} className={index === 0 ? styles.barVersion : undefined}>
            {fact}
          </span>
        ))}
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
