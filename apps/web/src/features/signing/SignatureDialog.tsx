"use client";

import { useState } from "react";

import { fieldErrors, formError } from "@/shared/api/errors";
import { SignatureMark } from "@/shared/document/SignatureMark";
import { Button, Dialog, Notice, Radio, SignaturePad, TextButton, TextField, type Stroke } from "@/shared/ui";

import type { Adopted, SignatureIn } from "./api";

type Font = { id: string; family: string; url: string };

type Kind = Adopted["kind"];

const WORDS: Record<Kind, { title: string; noun: string }> = {
  signature: { title: "Your signature", noun: "signature" },
  initials: { title: "Your initials", noun: "initials" },
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
 * Adopt a signature or initials (Phase 8 §5.1): type it in a handwriting style, or draw it. Typing
 * is offered only when there are styles to type in.
 */
export function SignatureDialog({
  kind,
  name,
  fonts,
  saved,
  phone,
  onAdopt,
  onClose,
}: {
  kind: Kind;
  name: string;
  fonts: readonly Font[];
  /** A countersigner's saved one (Phase 8 §5.4): offered to use again, still adopted here. */
  saved?: Adopted | undefined;
  phone: boolean;
  onAdopt: (body: SignatureIn) => Promise<unknown>;
  onClose: () => void;
}) {
  const canType = fonts.length > 0;
  const [tab, setTab] = useState<"type" | "draw">(canType ? "type" : "draw");
  const [text, setText] = useState(kind === "initials" ? initialsOf(name) : name);
  const [font, setFont] = useState(fonts[0]?.id ?? "");
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const words = WORDS[kind];

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
  const problem = error ? (Object.values(fieldErrors(error))[0] ?? formError(error)) : null;

  return (
    <Dialog
      title={words.title}
      placement={phone ? "bottom" : "center"}
      onClose={onClose}
      actions={
        <>
          <Button onClick={adopt} disabled={!ready || busy}>
            Adopt and sign
          </Button>
          <TextButton onClick={onClose}>Cancel</TextButton>
        </>
      }
    >
      {saved ? (
        <TextButton
          onClick={() => {
            setTab(saved.method === "typed" ? "type" : "draw");
            if (saved.method === "typed") {
              setText(saved.text ?? "");
              setFont(saved.font?.id ?? font);
            } else setStrokes((saved.strokes ?? []) as Stroke[]);
          }}
        >
          {`Use my saved ${words.noun}`}
        </TextButton>
      ) : null}
      {canType ? (
        <div role="tablist" aria-label={`How to give your ${words.noun}`}>
          <TextButton role="tab" aria-selected={tab === "type"} onClick={() => setTab("type")}>
            Type
          </TextButton>{" "}
          <TextButton role="tab" aria-selected={tab === "draw"} onClick={() => setTab("draw")}>
            Draw
          </TextButton>
        </div>
      ) : null}
      {tab === "type" ? (
        <>
          <TextField label={kind === "initials" ? "Initials" : "Full name"} value={text} maxLength={100} onChange={(event) => setText(event.target.value)} />
          <div role="radiogroup" aria-label="Style">
            {fonts.map((face) => (
              <Radio key={face.id} name="style" checked={font === face.id} onChange={() => setFont(face.id)}>
                <SignatureMark mark={{ method: "typed", text: text || " ", font: face }} width={260} height={56} />
              </Radio>
            ))}
          </div>
        </>
      ) : (
        <>
          <SignaturePad label={`Draw your ${words.noun}`} strokes={strokes} onChange={setStrokes} />
          <TextButton onClick={() => setStrokes([])} disabled={strokes.length === 0}>
            Clear
          </TextButton>
        </>
      )}
      <p>By selecting Adopt and sign, I agree this is my electronic {words.noun}.</p>
      {problem ? <Notice tone="warning">{problem}</Notice> : null}
    </Dialog>
  );
}
