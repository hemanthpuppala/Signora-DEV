"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./stepDialog.module.css";

/**
 * A task in a few steps, in one modal (Phase 7 §2: sending): a progress line at the top (numbered
 * steps; finished ones ticked; the current one marked for assistive technology too), one step's
 * content at a time with a subtle transition (none when the person asks for reduced motion), and
 * at the bottom Back and the step's own actions. On the native ``<dialog>`` like ``Dialog``: focus
 * stays inside, Esc asks ``onClose``.
 */
export function StepDialog({
  title,
  steps,
  current,
  onStep,
  onClose,
  children,
  actions,
  back,
}: {
  title: string;
  steps: readonly string[];
  /** 0-based. */
  current: number;
  /** Going back to a finished step from the progress line (later steps are reached by Next). */
  onStep?: (step: number) => void;
  onClose: () => void;
  children: ReactNode;
  actions: ReactNode;
  back?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return undefined;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    return () => {
      if (typeof dialog.close === "function" && dialog.open) dialog.close();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className={styles.head}>
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        <button type="button" className={styles.close} aria-label="Close" onClick={onClose}>
          ×
        </button>
      </div>
      <ol className={styles.steps} aria-label="Steps">
        {steps.map((label, index) => {
          const done = index < current;
          const content = (
            <>
              <span className={styles.number} aria-hidden="true">
                {done ? "✓" : index + 1}
              </span>
              <span className={styles.label}>{label}</span>
            </>
          );
          return (
            <li
              key={label}
              className={cx(styles.step, done && styles.done, index === current && styles.current)}
              aria-current={index === current ? "step" : undefined}
            >
              {done && onStep ? (
                <button type="button" className={styles.stepButton} onClick={() => onStep(index)}>
                  {content}
                </button>
              ) : (
                content
              )}
            </li>
          );
        })}
      </ol>
      <div key={current} className={styles.body}>
        {children}
      </div>
      <div className={styles.foot}>
        <div>{back}</div>
        <div className={styles.actions}>{actions}</div>
      </div>
    </dialog>
  );
}
