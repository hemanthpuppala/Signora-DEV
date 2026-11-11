"use client";

import { useEffect, useId, useRef, type CSSProperties, type ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./stepDialog.module.css";

/**
 * A task in a few steps, in one modal (Phase 7 §2: sending): a progress line at the top (a track
 * of numbered stops, filled up to the current one; the current one marked for assistive technology too; a stop
 * that still needs the person carries its count), one step's
 * content at a time with a subtle transition (none when the person asks for reduced motion), and
 * at the bottom Back and the step's own actions. On the native ``<dialog>`` like ``Dialog``: focus
 * stays inside, Esc asks ``onClose``.
 */
export function StepDialog({
  title,
  aside,
  steps,
  attention,
  current,
  onStep,
  onClose,
  children,
  actions,
  back,
}: {
  title: string;
  /** Beside the title: a quiet way to another dialog for the same job ("Send in bulk instead"). */
  aside?: ReactNode;
  steps: readonly string[];
  /**
   * Steps that still need the person, by index, each with a few words or a count ("40"): shown
   * on its stop, and said to assistive technology ("Fix, 40 to fix").
   */
  attention?: Readonly<Record<number, string>>;
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
        <div className={styles.headEnd}>
          {aside}
          <button type="button" className={styles.close} aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
      </div>
      <ol className={styles.steps} aria-label="Steps" style={{ "--steps": steps.length } as CSSProperties}>
        {steps.map((label, index) => {
          const done = index < current;
          const content = (
            <>
              <span className={styles.node} aria-hidden="true" />
              <span className={styles.meta}>
                <span className={styles.number} aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className={styles.label}>
                  {label}
                  {attention?.[index] ? (
                    <span className={styles.attention}>
                      <span className={styles.doneText}>, </span>
                      {attention[index]}
                      <span className={styles.doneText}> to fix</span>
                    </span>
                  ) : null}
                </span>
                {done ? <span className={styles.doneText}>, done</span> : null}
              </span>
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
