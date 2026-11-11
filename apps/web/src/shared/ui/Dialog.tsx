"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

import styles from "./dialog.module.css";

/**
 * A modal question on the native ``<dialog>`` (focus moves in and stays in, Esc closes, the page
 * behind is inert). Rendered only while open; ``onClose`` runs on Esc as on a dismiss button.
 */
export function Dialog({
  title,
  children,
  actions,
  onClose,
  placement = "center",
}: {
  title: string;
  children: ReactNode;
  actions: ReactNode;
  onClose: () => void;
  /** "bottom": a sheet along the bottom of a phone's screen (Phase 8 §4.4). */
  placement?: "center" | "bottom";
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
      className={placement === "bottom" ? `${styles.dialog} ${styles.sheet}` : styles.dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <h2 id={titleId} className={styles.title}>
        {title}
      </h2>
      <div className={styles.body}>{children}</div>
      <div className={styles.actions}>{actions}</div>
    </dialog>
  );
}
