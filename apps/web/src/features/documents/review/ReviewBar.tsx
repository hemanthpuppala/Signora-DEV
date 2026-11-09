"use client";

import { useState } from "react";

import { ApiError, formError } from "@/shared/api/errors";
import { Button, Dialog, Notice, SmallText, TextButton } from "@/shared/ui";

import type { Review } from "./useReview";
import styles from "./review.module.css";
import type { ReviewWarning } from "./ThingsToCheck";

const changesWords = (n: number) => `${n} unsaved ${n === 1 ? "change" : "changes"}`;

/**
 * The top of the fields panel (Phase 6 §7): the save bar while there are unsaved changes, what went
 * wrong with a save, and Approve, which is disabled until the changes are saved (what is approved
 * is what is saved). An approved version offers "Edit fields"; saving that edit makes the next
 * version, and the bar says so.
 */
export function ReviewBar({
  review,
  number,
  nextNumber,
  warnings,
  onShow,
}: {
  review: Review;
  number: number;
  nextNumber: number;
  warnings: readonly ReviewWarning[];
  onShow: (fieldId: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const { changes, editing, approved, inReview, problem } = review;

  return (
    <div className={styles.bar}>
      {approved && !editing ? (
        <div className={styles.barLine}>
          <span>Approved: its fields are frozen.</span>
          <Button variant="quiet" compact onClick={review.startEditing}>
            Edit fields
          </Button>
        </div>
      ) : null}
      {approved && editing ? (
        <SmallText>{`Saving makes version ${nextNumber}. Version ${number} stays approved as it is.`}</SmallText>
      ) : null}
      {editing && changes > 0 ? (
        <div className={styles.saveBar} role="group" aria-label="Unsaved changes">
          <span className={styles.count}>{changesWords(changes)}</span>
          <TextButton disabled={!review.canUndo} onClick={review.undo}>
            Undo
          </TextButton>
          <TextButton onClick={review.discard}>Discard</TextButton>
          <Button compact loading={review.saving} loadingLabel="Saving…" onClick={review.save}>
            {approved ? `Save as version ${nextNumber}` : "Save"}
          </Button>
        </div>
      ) : null}
      {approved && editing && changes === 0 ? (
        <TextButton onClick={review.stopEditing}>Stop editing</TextButton>
      ) : null}
      {problem ? (
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
                  {item.fieldId ? (
                    <TextButton onClick={() => onShow(item.fieldId ?? "")}>{item.message}</TextButton>
                  ) : (
                    item.message
                  )}
                </li>
              ))}
            </ul>
          ) : null}
        </Notice>
      ) : null}
      {inReview && review.canApprove ? (
        <div className={styles.barLine}>
          <span>{warnings.length > 0 ? `${warnings.length} ${warnings.length === 1 ? "thing" : "things"} to check` : null}</span>
          <Button compact disabled={changes > 0} onClick={() => setConfirming(true)}>
            Approve version
          </Button>
        </div>
      ) : null}
      {inReview && review.canApprove && changes > 0 ? <SmallText>Save your changes to approve them.</SmallText> : null}
      {confirming ? (
        <ApproveDialog
          review={review}
          number={number}
          warnings={warnings}
          onClose={() => {
            setConfirming(false);
            review.approve.reset();
          }}
        />
      ) : null}
    </div>
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
