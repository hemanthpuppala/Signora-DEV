"use client";

import { useState } from "react";

import { fieldErrors, formError } from "@/shared/api/errors";
import { SignatureMark } from "@/shared/document/SignatureMark";
import { Button, Dialog, Notice, SignaturePad, TextButton, TextField, type Stroke } from "@/shared/ui";

import type { Adopted, SignatureIn } from "./api";
import styles from "./signing.module.css";

type Font = { id: string; family: string; url: string };
type Kind = Adopted["kind"];

const WORDS: Record<Kind, { title: string; noun: string; field: string }> = {
  signature: { title: "Your signature", noun: "signature", field: "Full name" },
  initials: { title: "Your initials", noun: "initials", field: "Initials" },
};

/** "MC" from "Maya Chen": the first letter of each word. */
export function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Adopt a signature or initials (Phase 8 §5.1): typed in a handwriting style, or drawn. A signature
 * is always shown on paper, as it will sit on the page: the styles are paper cards, the pad is
 * paper. Typing is offered only when there are styles to type in.
 */
export function SignatureDialog({
  kind,
  name,
  fonts,
  saved,
  onAdopt,
  onClose,
}: {
  kind: Kind;
  name: string;
  fonts: readonly Font[];
  /** A countersigner's saved one (Phase 8 §5.4): offered to use again, still adopted here. */
  saved?: Adopted | undefined;
  onAdopt: (body: SignatureIn) => Promise<unknown>;
  onClose: () => void;
}) {
  const canType = fonts.length > 0;
  const words = WORDS[kind];
  const [tab, setTab] = useState<"type" | "draw">(canType ? "type" : "draw");
  const [text, setText] = useState(kind === "initials" ? initialsOf(name) : name);
  const [font, setFont] = useState(fonts[0]?.id ?? "");
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const ready = tab === "type" ? text.trim().length > 0 && Boolean(font) : strokes.length > 0;
  const adopt = async () => {
    setBusy(true);
    setError(null);
    try {
      await onAdopt(tab === "type" ? { method: "typed", text: text.trim(), font } : { method: "drawn", strokes });
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  };
  const useSaved = () => {
    if (!saved) return;
    if (saved.method === "typed") {
      setTab("type");
      setText(saved.text ?? "");
      setFont(saved.font?.id ?? font);
    } else {
      setTab("draw");
      setStrokes((saved.strokes ?? []) as Stroke[]);
    }
  };
  const problem = error ? (Object.values(fieldErrors(error))[0] ?? formError(error)) : null;

  return (
    <Dialog
      title={words.title}
      onClose={onClose}
      actions={
        <>
          <Button onClick={adopt} disabled={!ready || busy}>
            {busy ? "Adopting…" : "Adopt and sign"}
          </Button>
          <TextButton onClick={onClose}>Cancel</TextButton>
        </>
      }
    >
      <div className={styles.adopt}>
        {canType ? (
          <div className={styles.switch} role="tablist" aria-label={`How to give your ${words.noun}`}>
            {(["type", "draw"] as const).map((one) => (
              <button
                key={one}
                type="button"
                role="tab"
                aria-selected={tab === one}
                className={styles.switchOption}
                onClick={() => setTab(one)}
              >
                {one === "type" ? "Type" : "Draw"}
              </button>
            ))}
          </div>
        ) : null}
        {saved ? (
          <TextButton onClick={useSaved}>{`Use my saved ${words.noun}`}</TextButton>
        ) : null}

        {tab === "type" ? (
          <>
            <TextField label={words.field} value={text} maxLength={100} onChange={(event) => setText(event.target.value)} />
            <div className={styles.styles} role="radiogroup" aria-label="Style">
              {fonts.map((face) => (
                <button
                  key={face.id}
                  type="button"
                  role="radio"
                  aria-checked={font === face.id}
                  aria-label={`${face.family} style`}
                  className={styles.styleCard}
                  onClick={() => setFont(face.id)}
                >
                  <SignatureMark mark={{ method: "typed", text: text.trim() || name, font: face }} width={240} height={52} />
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className={styles.drawing}>
            <SignaturePad label={`Draw your ${words.noun}`} strokes={strokes} onChange={setStrokes} />
            <TextButton onClick={() => setStrokes([])} disabled={strokes.length === 0}>
              Clear
            </TextButton>
          </div>
        )}

        <p className={styles.agree}>By selecting Adopt and sign, I agree this is my electronic {words.noun}.</p>
        {problem ? <Notice tone="warning">{problem}</Notice> : null}
      </div>
    </Dialog>
  );
}
