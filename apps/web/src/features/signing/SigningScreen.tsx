"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { fieldErrors, formError } from "@/shared/api/errors";
import { askedFields } from "@/shared/document/conditions";
import { FieldInput } from "@/shared/document/FieldInput";
import { typeset, useFontReady } from "@/shared/document/typeset";
import { ValuesOverlay, type Shown } from "@/shared/document/ValuesOverlay";
import { useTopLayer } from "@/shared/lib/topLayer";
import { useAnchored } from "@/shared/lib/useAnchored";
import { Button, Checkbox, Dialog, GuidePointer, Notice, PdfViewer, TextButton } from "@/shared/ui";

import {
  clearDraft,
  markViewed,
  pdfUrl,
  saveDraft,
  useSignerDocument,
  type SignerDocument,
  type SignerField,
  type SignerState,
} from "./api";
import { allValues, firstPlace, guided, guideStep, ownValue, pointerLabel, remaining, SIGNING_DATE, SIGNS } from "./guide";
import styles from "./signing.module.css";
import { SignerProblem } from "./SignerNotices";

type Place = SignerField["places"][number];
type Drafts = Record<string, string>;

const SAVE_AFTER_MS = 800; // a draft is saved once the person stops typing (§4.5)
const PHONE = "(max-width: 640px), (pointer: coarse)";

/** Types typed straight into their box on a computer (§4.4); the rest open an editor beside it. */
const IN_PLACE = new Set([
  "text", "full_name", "first_name", "last_name", "legal_name", "title", "company", "address",
  "email", "phone", "number", "currency", "percent", "day", "year", "url", "tax_id",
  "bank_account", "other",
]);

function usePhone(): boolean {
  return useSyncExternalStore(
    (changed) => {
      const query = window.matchMedia?.(PHONE);
      query?.addEventListener("change", changed);
      return () => query?.removeEventListener("change", changed);
    },
    () => window.matchMedia?.(PHONE).matches ?? false,
    () => false,
  );
}

function stillMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

/** Where a place sits over its page, in CSS pixels. */
function boxStyle(place: Place, scale: number) {
  const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = place.rect;
  return { left: x0 * scale, top: y0 * scale, width: (x1 - x0) * scale, height: (y1 - y0) * scale };
}

/** The signer's screen (Phase 8 §4): the document, their fields, the guide and the Submit block. */
export function SigningScreen({ state }: { state: SignerState }) {
  const id = state.recipient_id;
  const document = useSignerDocument(id);
  if (document.isError) return <SignerProblem error={document.error} />;
  if (!document.data) return <p className={styles.loading}>Opening the document…</p>;
  return <Loaded state={state} doc={document.data} />;
}

function Loaded({ state, doc }: { state: SignerState; doc: SignerDocument }) {
  const id = state.recipient_id;
  const phone = usePhone();
  const fontReady = useFontReady(doc.font);
  const [drafts, setDrafts] = useState<Drafts>(() =>
    Object.fromEntries(doc.fields.filter((f) => f.draft !== null).map((f) => [f.id, f.draft as string])),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [current, setCurrent] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const [focus, setFocus] = useState<{ page: number; rect: [number, number, number, number]; token: number } | null>(null);
  const [editing, setEditing] = useState<string | null>(null); // a field open in the sheet or beside its box
  const [target, setTarget] = useState<Element | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [later, setLater] = useState(false);
  const [atConfirm, setAtConfirm] = useState(false); // the guide points at the Submit block's box
  const timers = useRef(new Map<string, number>());
  const submitRef = useRef<HTMLElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);

  // The document was shown: recorded once, for the sender's timeline (§4.5).
  useEffect(() => {
    void markViewed(id).catch(() => undefined);
  }, [id]);

  const byId = useMemo(() => new Map(doc.fields.map((field) => [field.id, field])), [doc.fields]);
  const values = allValues(doc.fields, drafts);
  const asked = askedFields(doc.fields, values);
  const order = guided(doc.fields, drafts);
  const left = remaining(doc.fields, drafts);
  const step = guideStep(started, left.length);

  /** Keep a value locally at once, and save it as a draft once typing stops (or now). */
  function commit(field: SignerField, value: string, now = false) {
    setDrafts((was) => {
      const next = { ...was, [field.id]: value };
      if (!value) delete next[field.id];
      // A field no longer asked loses its value, here as on the server (§4.5).
      const stillAsked = askedFields(doc.fields, allValues(doc.fields, next));
      for (const other of doc.fields) if (other.mine && !stillAsked.has(other.id)) delete next[other.id];
      return next;
    });
    setErrors((was) => ({ ...was, [field.id]: "" }));
    window.clearTimeout(timers.current.get(field.id));
    const save = () => {
      const call = value ? saveDraft(id, field.id, value).then((saved) => saved.value) : clearDraft(id, field.id).then(() => "");
      call.then(
        (stored) => {
          if (stored !== value) setDrafts((was) => (was[field.id] === value ? { ...was, [field.id]: stored } : was));
        },
        (error: unknown) => setErrors((was) => ({ ...was, [field.id]: fieldErrors(error).value ?? formError(error) ?? "Not saved" })),
      );
    };
    if (now) save();
    else timers.current.set(field.id, window.setTimeout(save, SAVE_AFTER_MS));
  }

  /** Point at a field: scroll it into view, ring it, and (on a phone) open its sheet. */
  function guideTo(field: SignerField) {
    const place = firstPlace(field);
    if (!place) return;
    setStarted(true);
    setAtConfirm(false);
    setCurrent(field.id);
    setFocus({ page: place.page, rect: [...place.rect] as [number, number, number, number], token: Date.now() });
    if (phone && !SIGNS.has(field.holds)) setEditing(field.id);
  }

  function onGuide() {
    if (step === "complete") {
      setCurrent(null);
      submitRef.current?.scrollIntoView?.({ behavior: stillMotion() ? "auto" : "smooth", block: "center" });
      setTarget(confirmRef.current);
      setAtConfirm(true);
      confirmRef.current?.focus({ preventScroll: true });
      return;
    }
    const at = current ? order.findIndex((field) => field.id === current) : -1;
    const next = left.find((field) => order.indexOf(field) > at) ?? left[0];
    if (next) guideTo(next);
  }

  // The pointer follows the field once its page is drawn (pages are drawn as they come into view).
  useEffect(() => {
    if (!current) return undefined;
    let frames = 0;
    let handle = 0;
    const look = () => {
      const element = window.document.querySelector(`[data-field="${current}"]`);
      if (element) {
        setTarget(element);
        if (!phone && element instanceof HTMLElement) element.focus({ preventScroll: true });
      } else if (frames++ < 120) handle = requestAnimationFrame(look);
    };
    look();
    return () => cancelAnimationFrame(handle);
  }, [current, focus, phone]);

  const pointing = current ? byId.get(current) : null;
  const pointerOn = pointing && !ownValue(pointing, drafts) ? pointerLabel(pointing) : atConfirm && !confirmed ? "Tick to confirm" : null;

  const missing =
    left.length > 0
      ? `${left.length} ${left.length === 1 ? "field" : "fields"} left`
      : !confirmed
        ? "Tick the box to confirm"
        : null;

  if (later) {
    return (
      <main className={styles.later}>
        <h1 className={styles.heading}>Your progress is saved.</h1>
        <p>Open the link in your email to continue. It works until the request closes.</p>
      </main>
    );
  }

  const editingField = editing ? byId.get(editing) : undefined;
  return (
    <div className={styles.screen}>
      <header className={styles.bar}>
        <div className={styles.titles}>
          <span className={styles.company}>{state.company}</span>
          <span className={styles.title}>{state.title}</span>
        </div>
        <span className={styles.count} aria-live="polite">
          {left.length > 0 ? `${left.length} ${left.length === 1 ? "field" : "fields"} left` : "All filled"}
        </span>
        {step !== "complete" || !confirmed ? (
          <Button onClick={onGuide}>{step === "start" ? "Start" : step === "next" ? "Next" : "Complete"}</Button>
        ) : null}
        <TextButton onClick={() => setLater(true)}>Finish later</TextButton>
      </header>

      <PdfViewer
        url={pdfUrl(id)}
        pages={doc.pages}
        label={state.title}
        focus={focus}
        renderOverlay={({ page, scale }) => (
          <Overlay
            page={page}
            scale={scale}
            doc={doc}
            drafts={drafts}
            asked={asked}
            phone={phone}
            fontReady={fontReady}
            errors={errors}
            current={current}
            onType={(field, value) => commit(field, value)}
            onSet={(field, value) => commit(field, value, true)}
            onOpen={(field) => {
              setCurrent(field.id);
              setEditing(field.id);
            }}
            onFocusField={(field) => setCurrent(field.id)}
          />
        )}
      />

      <section ref={submitRef} className={styles.submit} aria-label="Sign and submit">
        <p className={styles.statement}>
          By selecting Sign and submit, I agree to sign this document electronically and to be bound by it, the same as a
          handwritten signature.
        </p>
        <Checkbox ref={confirmRef} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)}>
          I&apos;ve reviewed this document and this is my signature
        </Checkbox>
        <Button disabled={missing !== null}>Sign and submit</Button>
        {missing ? <p className={styles.missing}>{missing}</p> : null}
      </section>

      {pointerOn && target ? <GuidePointer target={target} label={pointerOn} /> : null}

      {editingField ? (
        <Editor
          field={editingField}
          value={ownValue(editingField, drafts)}
          phone={phone}
          error={errors[editingField.id]}
          onCancel={() => setEditing(null)}
          onSave={(value) => {
            commit(editingField, value, true);
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}

/** One page's fields over the painted page: the person's own to fill, the rest drawn or boxed. */
function Overlay({
  page,
  scale,
  doc,
  drafts,
  asked,
  phone,
  fontReady,
  errors,
  current,
  onType,
  onSet,
  onOpen,
  onFocusField,
}: {
  page: number;
  scale: number;
  doc: SignerDocument;
  drafts: Drafts;
  asked: Set<string>;
  phone: boolean;
  fontReady: boolean;
  errors: Record<string, string>;
  current: string | null;
  onType: (field: SignerField, value: string) => void;
  onSet: (field: SignerField, value: string) => void;
  onOpen: (field: SignerField) => void;
  onFocusField: (field: SignerField) => void;
}) {
  const shown: Shown[] = [];
  const boxes: React.ReactNode[] = [];
  for (const field of doc.fields) {
    if (!asked.has(field.id)) continue;
    const here = field.places.filter((place) => place.page === page);
    if (here.length === 0) continue;
    const own = field.mine && !field.locked;
    const value = field.mine ? ownValue(field, drafts) : (field.value ?? "");
    const typedHere = own && !phone && IN_PLACE.has(field.holds);
    if (value && !SIGNS.has(field.holds) && field.holds !== SIGNING_DATE) {
      // Drawn as the signed PDF draws it, except in a box being typed into.
      const drawn = typedHere ? field.places.filter((place) => place !== field.places[0]) : field.places;
      shown.push({ places: drawn, holds: field.holds, value, format: field.format });
    }
    here.forEach((place, index) => {
      const key = `${field.id}-${index}`;
      const style = boxStyle(place, scale);
      const first = place === field.places[0];
      const marker = first ? { "data-field": field.id } : {};
      const filled = Boolean(value);
      const label = `${field.label}${field.required ? " (required)" : ""}`;
      if (!field.mine) {
        if (field.hidden || (!value && field.party_id)) {
          const party = doc.parties.find((p) => p.id === field.party_id);
          const words =
            field.hidden === "private" ? "Private" : field.hidden === "countersigner" ? `${party?.label ?? "Countersigner"} signs here` : (party?.label ?? "");
          boxes.push(
            <span key={key} className={styles.faint} style={style}>
              <span className={styles.faintLabel}>{words}</span>
            </span>,
          );
        }
        return;
      }
      if (!own) return; // locked: drawn above
      if (field.holds === SIGNING_DATE) {
        boxes.push(
          <span key={key} className={`${styles.box} ${styles.auto}`} style={style}>
            <span className={styles.faintLabel}>Added when you sign</span>
          </span>,
        );
        return;
      }
      const cls = `${styles.box} ${filled ? styles.filled : styles.todo} ${current === field.id ? styles.current : ""}`;
      if (field.holds === "checkbox" || (field.holds === "choice" && place.option_value !== null)) {
        const on = field.holds === "checkbox" ? value === "true" : value === place.option_value;
        boxes.push(
          <button
            key={key}
            type="button"
            className={cls}
            style={style}
            role={field.holds === "checkbox" ? "checkbox" : "radio"}
            aria-checked={on}
            aria-label={field.holds === "choice" ? `${field.label}: ${place.option_value}` : label}
            onClick={() => {
              onFocusField(field);
              onSet(field, field.holds === "checkbox" ? (on ? "" : "true") : on ? "" : (place.option_value ?? ""));
            }}
            {...marker}
          />,
        );
        return;
      }
      if (typedHere && first) {
        const set = typeset(value || "M", place.rect, place.text_size, doc.font, doc.fit);
        boxes.push(
          <span key={key} className={styles.inPlace} style={style}>
            <input
              className={`${cls} ${styles.input}`}
              aria-label={label}
              aria-invalid={errors[field.id] ? true : undefined}
              value={value}
              autoComplete="off"
              style={{
                fontFamily: fontReady ? `"${doc.font.family}", var(--sans)` : undefined,
                fontSize: set.size * scale,
              }}
              onFocus={() => onFocusField(field)}
              onChange={(event) => onType(field, event.target.value)}
              {...marker}
            />
            {errors[field.id] ? <span className={styles.boxError} role="alert">{errors[field.id]}</span> : null}
          </span>,
        );
        return;
      }
      if (typedHere) return; // a second place of a typed field: drawn above
      boxes.push(
        <button
          key={key}
          type="button"
          className={cls}
          style={style}
          aria-label={SIGNS.has(field.holds) ? `${field.label}: sign here` : `${label}: ${filled ? "change" : "fill in"}`}
          onClick={() => onOpen(field)}
          {...marker}
        >
          {SIGNS.has(field.holds) ? <span className={styles.sign}>{field.holds === "initials" ? "Initial" : "Sign"}</span> : null}
        </button>,
      );
    });
  }
  return (
    <>
      <ValuesOverlay page={page} scale={scale} shown={shown} font={doc.font} fit={doc.fit} />
      {boxes}
    </>
  );
}

/** A field's input: a sheet along the bottom on a phone, a panel beside the box on a computer. */
function Editor({
  field,
  value,
  phone,
  error,
  onCancel,
  onSave,
}: {
  field: SignerField;
  value: string;
  phone: boolean;
  error: string | undefined;
  onCancel: () => void;
  onSave: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const input = (
    <FieldInput field={field} value={draft} onChange={setDraft} error={error || undefined} inlineDate />
  );
  const actions = (
    <>
      <Button onClick={() => onSave(draft)}>Save</Button>
      <TextButton onClick={onCancel}>Cancel</TextButton>
    </>
  );
  if (phone || SIGNS.has(field.holds)) {
    return (
      <Dialog title={`Enter ${field.label}`} placement={phone ? "bottom" : "center"} onClose={onCancel} actions={actions}>
        {SIGNS.has(field.holds) ? <Notice tone="info">Signing comes with your signature, next.</Notice> : input}
      </Dialog>
    );
  }
  return <Beside field={field} onCancel={onCancel} actions={actions}>{input}</Beside>;
}

/** A small panel opened beside a field's box on a computer (a date's calendar, a list). */
function Beside({ field, onCancel, actions, children }: { field: SignerField; onCancel: () => void; actions: React.ReactNode; children: React.ReactNode }) {
  const anchor = useRef<HTMLElement | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const canPop = useTopLayer();
  useLayoutEffect(() => {
    anchor.current = window.document.querySelector(`[data-field="${field.id}"]`);
  }, [field.id]);
  const place = useAnchored(true, anchor, panel, { canPop, maxHeight: 520 });
  return (
    <div
      ref={panel}
      className={styles.beside}
      role="dialog"
      aria-label={`Enter ${field.label}`}
      popover={canPop ? "manual" : undefined}
      style={place}
      onKeyDown={(event) => {
        if (event.key === "Escape") onCancel();
      }}
    >
      {children}
      <div className={styles.besideActions}>{actions}</div>
    </div>
  );
}
