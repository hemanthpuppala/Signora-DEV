"use client";

import { useState } from "react";

import { Select, TextButton } from "@/shared/ui";

import { HOLD_GROUPS, HOLDS } from "../fields";
import type { Holds } from "./editor";
import styles from "./review.module.css";

const QUICK: readonly Holds[] = ["signature", "initials", "date_signed", "full_name", "text", "checkbox"];

/** What the next press on a page makes: a new field of a type, or another place of a field. */
export type Tool = { kind: "field"; holds: Holds } | { kind: "place"; fieldId: string; label: string };

/**
 * "+ Add field" (Phase 6 §5, as in DocuSign): the common types, and "More…" for the rest.
 * While a tool is chosen the bar says what a click does; Escape or Cancel puts it away.
 */
export function Palette({ tool, onTool }: { tool: Tool | null; onTool: (tool: Tool | null) => void }) {
  const [open, setOpen] = useState(false);
  if (tool) {
    const what = tool.kind === "field" ? HOLDS[tool.holds] : `another place of ${tool.label}`;
    return (
      <span className={styles.palette} role="status">
        <span>{`Click on a page to place ${tool.kind === "field" ? `a ${what}` : what}, or drag to draw it`}</span>
        <TextButton onClick={() => onTool(null)}>Cancel</TextButton>
      </span>
    );
  }
  if (!open) {
    return <TextButton onClick={() => setOpen(true)}>+ Add field</TextButton>;
  }
  const pick = (holds: Holds) => {
    setOpen(false);
    onTool({ kind: "field", holds });
  };
  const more = HOLD_GROUPS.flatMap((group) =>
    group.holds.filter((holds) => !QUICK.includes(holds)).map((holds) => ({ value: holds, label: `${HOLDS[holds]} · ${group.label}` })),
  );
  return (
    <span className={styles.palette} role="group" aria-label="Add field">
      {QUICK.map((holds) => (
        <TextButton key={holds} onClick={() => pick(holds)}>
          {HOLDS[holds]}
        </TextButton>
      ))}
      <Select label="More…" options={more} value={null} placeholder="More…" onChange={(value) => pick(value as Holds)} />
      <TextButton onClick={() => setOpen(false)}>Close</TextButton>
    </span>
  );
}
