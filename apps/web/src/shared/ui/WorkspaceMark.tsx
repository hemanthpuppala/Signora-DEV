"use client";

import { useState } from "react";

import styles from "./shell.module.css";

export type WorkspaceMarkProps = {
  name: string;
  /** The company's logo; without one, or if it fails to load, the name shows instead. */
  logoUrl?: string | null;
};

/** The company after the Signora mark: its logo when it has one, otherwise its name. */
export function WorkspaceMark({ name, logoUrl }: WorkspaceMarkProps) {
  const [failed, setFailed] = useState<string | null>(null);
  if (logoUrl && failed !== logoUrl) {
    return (
      <span className={styles.workspace}>
        {/* eslint-disable-next-line @next/next/no-img-element -- our own small PNG, already sized */}
        <img className={styles.workspaceLogo} src={logoUrl} alt={name} onError={() => setFailed(logoUrl)} />
      </span>
    );
  }
  return <span className={styles.workspace}>{name}</span>;
}
