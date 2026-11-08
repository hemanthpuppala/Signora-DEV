"use client";

import { useId, useState, type DragEvent } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./dropzone.module.css";

const ONE_AT_A_TIME = "Drop one file at a time";

/**
 * Takes one file, dropped or chosen (prototype .drop). Several dropped at once are refused with a
 * message: each upload is one file (Phase 4 LLD §2.4). ``accept`` only filters the file picker;
 * the server checks the real type.
 */
export function Dropzone({
  title,
  hint,
  accept,
  disabled = false,
  onFile,
}: {
  title: string;
  hint: string;
  accept: string;
  disabled?: boolean;
  onFile: (file: File) => void;
}) {
  const id = useId();
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const take = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (files.length > 1) {
      setError(ONE_AT_A_TIME);
      return;
    }
    setError(null);
    const [file] = files;
    if (file) onFile(file);
  };
  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    if (!disabled) take(event.dataTransfer.files);
  };

  return (
    <label
      htmlFor={id}
      className={cx(styles.drop, dragging && styles.dragging, disabled && styles.disabled)}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <span className={styles.title}>{title}</span>
      <span className={styles.hint}>{hint}</span>
      {error ? (
        <span className={styles.error} role="alert">
          {error}
        </span>
      ) : null}
      <input
        id={id}
        className={styles.input}
        type="file"
        accept={accept}
        disabled={disabled}
        onChange={(event) => {
          take(event.target.files);
          event.target.value = ""; // the same file can be chosen again
        }}
      />
    </label>
  );
}
