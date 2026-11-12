"use client";

import { Button, Notice, TextButton } from "@/shared/ui";

import styles from "./review.module.css";

/** Where a flagged field stands in the checklist, and the ways on from it. */
export type LookStep = {
  position: number; // 1-based, among the fields still needing a look
  total: number;
  onNext: () => void;
  /** Accept the field as found and go on; ``null`` for people who only read the fields. */
  onLooksRight: (() => void) | null;
};

/**
 * A flagged field's notice (Phase 6 §2.2): why it needs a look, then Looks right (accept it as
 * found, and go on to the next) and Next. Changing the field clears the flag as well.
 */
export function NeedsALook({ reason, step }: { reason: string; step: LookStep | null }) {
  const sentence = `${reason.charAt(0).toUpperCase()}${reason.slice(1)}.`;
  return (
    <Notice
      tone="warning"
      title="Needs a look"
      action={
        step ? (
          <div className={styles.lookActions}>
            {step.onLooksRight ? (
              <Button variant="quiet" compact onClick={step.onLooksRight}>
                Looks right
              </Button>
            ) : null}
            {step.total > 1 ? <TextButton onClick={step.onNext}>{`Next · ${step.position} of ${step.total}`}</TextButton> : null}
          </div>
        ) : undefined
      }
    >
      {sentence}
    </Notice>
  );
}
