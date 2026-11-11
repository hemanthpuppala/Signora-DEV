"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { fieldErrors, formError } from "@/shared/api/errors";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import { askedFields } from "@/shared/document/conditions";
import { FieldInput } from "@/shared/document/FieldInput";
import { typeset, useFontReady } from "@/shared/document/typeset";
import { ValuesOverlay, type Shown } from "@/shared/document/ValuesOverlay";
import { useTopLayer } from "@/shared/lib/topLayer";
import { useAnchored } from "@/shared/lib/useAnchored";
import {
  Button,
  Checkbox,
  DetailsPane,
  Dialog,
  GuidePointer,
  PdfViewer,
  TextButton,
  TopBar,
  ViewerLayout,
  ViewerPane,
} from "@/shared/ui";

import { useQueryClient } from "@tanstack/react-query";

import { SignatureMark, type Mark } from "@/shared/document/SignatureMark";

import {
  adoptSignature,
  applyToAll,
  clearDraft,
  markViewed,
  pdfUrl,
  saveDraft,
  signatureKey,
  signerKey,
  submitSigning,
  useSignature,
  useSignerDocument,
  type Adopted,
  type SignerDocument,
  type SignerField,
  type SignerState,
} from "./api";
import { allValues, firstPlace, guided, guideStep, ownValue, pointerLabel, remaining, SIGNING_DATE, SIGNS } from "./guide";
import styles from "./signing.module.css";
import { DeclineDialog, Declined } from "./Decline";
import { SignatureDialog } from "./SignatureDialog";
import { SignerProblem } from "./SignerNotices";

type Place = SignerField["places"][number];
type Drafts = Record<string, string>;

const SAVE_AFTER_MS = 800; // a draft is saved once the person stops typing (§4.5)
/** A small screen, or a finger: one column, a dock and a dialog per field (Phase 8 §4.4). */
const COMPACT = "(max-width: 959px), (pointer: coarse)";

/** Types typed straight into their box on a computer (§4.4); the rest open an editor beside it. */
const IN_PLACE = new Set([
  "text", "full_name", "first_name", "last_name", "legal_name", "title", "company", "address",
  "email", "phone", "number", "currency", "percent", "day", "year", "url", "tax_id",
  "bank_account", "other",
]);

function useCompact(): boolean {
  return useSyncExternalStore(
    (changed) => {
      const query = window.matchMedia?.(COMPACT);
      query?.addEventListener("change", changed);
      return () => query?.removeEventListener("change", changed);
    },
    () => window.matchMedia?.(COMPACT).matches ?? false,
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
  const compact = useCompact();
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
  const [reviewing, setReviewing] = useState(false); // a small screen's Sign and submit dialog
  const [declining, setDeclining] = useState(false);
  const [declined, setDeclined] = useState(false);
  const [atConfirm, setAtConfirm] = useState(false); // the guide points at the Submit block's box
  const queryClient = useQueryClient();
  const signature = useSignature(id);
  const marks = useMemo(() => marksOf(signature.data?.adopted ?? []), [signature.data]);
  // Sign and submit: one key per press, kept until a definite answer (backbone §3.6).
  const submit = useIdempotentAction<null, unknown>(`sign-submit:${id}`, (_, key) => submitSigning(id, key), {
    persistInput: false,
  });
  const submitted = submit.state.status === "success";
  useEffect(() => {
    if (submitted) void queryClient.invalidateQueries({ queryKey: signerKey(id) }); // to the done screen
  }, [submitted, queryClient, id]);
  // The server's word on each field goes to its box, and the guide to the first of them: once per
  // refusal, noticed while rendering (React's pattern for state that follows a new value).
  const refusal = submit.state.error;
  const [seenRefusal, setSeenRefusal] = useState<unknown>(null);
  if (refusal && refusal !== seenRefusal) {
    setSeenRefusal(refusal);
    const named = fieldErrors(refusal);
    setErrors((was) => ({ ...was, ...named }));
    const first = doc.fields.find((field) => named[field.id]);
    if (first) pointAt(first);
  }
  // Adopting a signature or initials: then sign one place, every place, or none (a change).
  const [adopting, setAdopting] = useState<{ kind: Adopted["kind"]; then: SignerField | "all" | null } | null>(null);
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

  /** A signature or initials place: signed by a tap once adopted; the first time, adopt it. */
  function sign(field: SignerField) {
    const kind = field.holds as Adopted["kind"];
    setCurrent(field.id);
    if (marks[kind]) commit(field, ownValue(field, drafts) ? "" : "signed", true);
    else setAdopting({ kind, then: field });
  }

  async function signAll(kind: Adopted["kind"]) {
    if (!marks[kind]) {
      setAdopting({ kind, then: "all" });
      return;
    }
    await applyToAll(id, kind);
    setDrafts((was) => {
      const next = { ...was };
      for (const field of doc.fields) if (field.mine && field.holds === kind && asked.has(field.id)) next[field.id] = "signed";
      return next;
    });
  }

  async function adopted(kind: Adopted["kind"], then: SignerField | "all" | null, body: Parameters<typeof adoptSignature>[2]) {
    await adoptSignature(id, kind, body);
    await queryClient.invalidateQueries({ queryKey: signatureKey(id) });
    setAdopting(null);
    if (then === "all") await applyToAll(id, kind).then(() =>
      setDrafts((was) => {
        const next = { ...was };
        for (const field of doc.fields) if (field.mine && field.holds === kind && asked.has(field.id)) next[field.id] = "signed";
        return next;
      }),
    );
    else if (then) commit(then, "signed", true);
  }

  /** Scroll a field into view and ring it (state only: safe while rendering). */
  function pointAt(field: SignerField) {
    const place = firstPlace(field);
    if (!place) return;
    setStarted(true);
    setAtConfirm(false);
    setCurrent(field.id);
    const rect = [...place.rect] as [number, number, number, number];
    setFocus((was) => ({ page: place.page, rect, token: (was?.token ?? 0) + 1 }));
  }

  /** Point at a field; on a small screen, open it to fill (a signature place: sign it). */
  function guideTo(field: SignerField) {
    pointAt(field);
    if (SIGNS.has(field.holds)) {
      if (!marks[field.holds as Adopted["kind"]]) setAdopting({ kind: field.holds as Adopted["kind"], then: field });
      else if (compact) sign(field); // the bar's "Sign here" is the tap
    } else if (compact) setEditing(field.id);
  }

  /** The next required field still empty after ``from`` in reading order, else the first. */
  function nextAfter(from: string | null): SignerField | undefined {
    const at = from ? order.findIndex((field) => field.id === from) : -1;
    return left.find((field) => field.id !== from && order.indexOf(field) > at) ?? left.find((field) => field.id !== from);
  }

  function onGuide() {
    if (step === "complete") {
      setCurrent(null);
      if (compact) {
        setReviewing(true);
        return;
      }
      setAtConfirm(true);
      submitRef.current?.scrollIntoView?.({ behavior: stillMotion() ? "auto" : "smooth", block: "nearest" });
      confirmRef.current?.focus({ preventScroll: true });
      return;
    }
    const next = nextAfter(current);
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
        if (!compact && element instanceof HTMLElement) element.focus({ preventScroll: true });
      } else if (frames++ < 120) handle = requestAnimationFrame(look);
    };
    look();
    return () => cancelAnimationFrame(handle);
  }, [current, focus, compact]);

  const dialogOpen = Boolean(adopting || editing || declining || reviewing);
  const pointing = current ? byId.get(current) : null;
  // Only on a computer, only at a field on the page, and never over a dialog.
  const pointerOn = !compact && !dialogOpen && pointing && !ownValue(pointing, drafts) ? pointerLabel(pointing) : null;

  const missing =
    left.length > 0
      ? `${left.length} ${left.length === 1 ? "field" : "fields"} left`
      : !confirmed
        ? "Tick the box to confirm"
        : null;

  if (declined) return <Declined company={state.company} />;
  if (later) {
    return (
      <main className={styles.later}>
        <h1 className={styles.heading}>Your progress is saved.</h1>
        <p>Open the link in your email to continue. It works until the request closes.</p>
      </main>
    );
  }

  const mine = doc.fields.filter((field) => field.mine && asked.has(field.id) && field.holds !== SIGNING_DATE);
  const done = mine.filter((field) => ownValue(field, drafts)).length;
  const signPlaces = (kind: Adopted["kind"]) => mine.filter((field) => field.holds === kind).length;
  const nextField = step === "complete" ? undefined : nextAfter(current);
  const guideWords =
    step === "complete"
      ? compact
        ? "Review and sign"
        : "Complete"
      : nextField && SIGNS.has(nextField.holds) && compact
        ? nextField.holds === "initials"
          ? "Initial here"
          : "Sign here"
        : step === "start"
          ? "Start"
          : "Next";

  const statement = (
    <>
      <p className={styles.statement}>
        By selecting Sign and submit, I agree to sign this document electronically and to be bound by it, the same as a
        handwritten signature.
      </p>
      <Checkbox ref={confirmRef} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)}>
        I&apos;ve reviewed this document and this is my signature
      </Checkbox>
      <Button disabled={missing !== null || submit.isPending} onClick={() => submit.run(null)}>
        {submit.isPending ? "Signing…" : "Sign and submit"}
      </Button>
      {missing ? <p className={styles.missing}>{missing}</p> : null}
      {refusal && !Object.keys(fieldErrors(refusal)).length ? (
        <p className={styles.missing} role="alert">
          {formError(refusal)}
        </p>
      ) : null}
    </>
  );

  const viewer = (
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
          compact={compact}
          fontReady={fontReady}
          errors={errors}
          current={current}
          onType={(field, value) => commit(field, value)}
          onSet={(field, value) => commit(field, value, true)}
          marks={marks}
          onOpen={(field) => {
            if (SIGNS.has(field.holds)) {
              sign(field);
              return;
            }
            setCurrent(field.id);
            setEditing(field.id);
          }}
          onFocusField={(field) => setCurrent(field.id)}
        />
      )}
    />
  );

  const editingField = editing ? byId.get(editing) : undefined;
  const dialogs = (
    <>
      {pointerOn && target ? <GuidePointer target={target} label={pointerOn} /> : null}
      {declining ? (
        <DeclineDialog recipientId={id} company={state.company} onDeclined={() => setDeclined(true)} onClose={() => setDeclining(false)} />
      ) : null}
      {adopting ? (
        <SignatureDialog
          kind={adopting.kind}
          name={state.name}
          fonts={signature.data?.fonts ?? []}
          saved={signature.data?.saved.find((one) => one.kind === adopting.kind)}
          onClose={() => setAdopting(null)}
          onAdopt={(body) => adopted(adopting.kind, adopting.then, body)}
        />
      ) : null}
      {editingField ? (
        <Editor
          field={editingField}
          value={ownValue(editingField, drafts)}
          compact={compact}
          position={positionOf(editingField, order)}
          error={errors[editingField.id]}
          onCancel={() => setEditing(null)}
          onSave={(value, andNext) => {
            commit(editingField, value, true);
            setEditing(null);
            if (andNext) {
              const after = order.filter((field) => field.id !== editingField.id && !ownValue(field, drafts));
              const next = after.find((field) => order.indexOf(field) > order.indexOf(editingField)) ?? after[0];
              if (next) guideTo(next);
              else if (compact) setReviewing(true);
            }
          }}
        />
      ) : null}
      {reviewing ? (
        <Dialog title="Sign and submit" onClose={() => setReviewing(false)} actions={<TextButton onClick={() => setReviewing(false)}>Back to the document</TextButton>}>
          <div className={styles.review}>{statement}</div>
        </Dialog>
      ) : null}
    </>
  );

  if (compact) {
    return (
      <div className={styles.compact}>
        <header className={styles.compactHead}>
          <div className={styles.titles}>
            <span className={styles.company}>{state.company}</span>
            <span className={styles.title}>{state.title}</span>
          </div>
          <div className={styles.quiet}>
            <TextButton onClick={() => setLater(true)}>Finish later</TextButton>
            <TextButton onClick={() => setDeclining(true)}>Decline</TextButton>
          </div>
        </header>
        {viewer}
        <nav className={styles.dock} aria-label="Signing">
          <span className={styles.count} aria-live="polite">
            {left.length > 0 ? `${left.length} ${left.length === 1 ? "field" : "fields"} left` : "All filled"}
          </span>
          <Button onClick={onGuide}>{guideWords}</Button>
        </nav>
        {dialogs}
      </div>
    );
  }

  return (
    <>
      <TopBar />
      <main className={styles.wide}>
        <ViewerLayout>
          <ViewerPane>{viewer}</ViewerPane>
          <DetailsPane>
            <header className={styles.panelHead}>
              <span className={styles.company}>{state.company}</span>
              <h1 className={styles.panelTitle}>{state.title}</h1>
              <span className={styles.from}>From {state.sender_name}</span>
            </header>

            <section className={styles.panelBlock} aria-label="Your fields">
              <div className={styles.progressLine}>
                <span aria-live="polite">{`${done} of ${mine.length} done`}</span>
                <Button compact onClick={onGuide}>
                  {guideWords}
                </Button>
              </div>
              <div className={styles.track} aria-hidden="true">
                <span style={{ width: `${mine.length ? (done / mine.length) * 100 : 100}%` }} />
              </div>
              <ul className={styles.fieldList}>
                {mine.map((field) => {
                  const filled = Boolean(ownValue(field, drafts));
                  return (
                    <li key={field.id}>
                      <button
                        type="button"
                        className={`${styles.fieldRow} ${current === field.id ? styles.fieldRowCurrent : ""}`}
                        onClick={() => guideTo(field)}
                      >
                        <span className={filled ? styles.tick : styles.dot} aria-hidden="true">
                          {filled ? "✓" : ""}
                        </span>
                        <span className={styles.fieldLabel}>{field.label}</span>
                        <span className={styles.fieldNote}>{field.locked ? "Filled" : field.required ? "Required" : "Optional"}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>

            {signPlaces("signature") + signPlaces("initials") > 0 ? (
              <section className={styles.panelBlock} aria-label="Your signature">
                <span className={styles.blockTitle}>Your signature</span>
                <div className={styles.signatureTile}>
                  {marks.signature ? (
                    <SignatureMark mark={marks.signature} width={260} height={64} />
                  ) : (
                    <span className={styles.tileEmpty}>Not adopted yet</span>
                  )}
                </div>
                <div className={styles.quiet}>
                  <TextButton onClick={() => setAdopting({ kind: "signature", then: null })}>
                    {marks.signature ? "Change" : "Adopt a signature"}
                  </TextButton>
                  {signPlaces("signature") > 1 ? <TextButton onClick={() => void signAll("signature")}>Sign all</TextButton> : null}
                  {signPlaces("initials") > 1 ? <TextButton onClick={() => void signAll("initials")}>Initial all</TextButton> : null}
                </div>
              </section>
            ) : null}

            <section ref={submitRef} className={`${styles.panelBlock} ${atConfirm && !confirmed ? styles.attention : ""}`} aria-label="Sign and submit">
              {statement}
            </section>

            <div className={styles.quiet}>
              <TextButton onClick={() => setLater(true)}>Finish later</TextButton>
              <TextButton onClick={() => setDeclining(true)}>Decline</TextButton>
            </div>
          </DetailsPane>
        </ViewerLayout>
      </main>
      {dialogs}
    </>
  );
}

/** One page's fields over the painted page: the person's own to fill, the rest drawn or boxed. */
function Overlay({
  page,
  scale,
  doc,
  drafts,
  asked,
  compact,
  fontReady,
  errors,
  current,
  marks,
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
  compact: boolean;
  fontReady: boolean;
  errors: Record<string, string>;
  current: string | null;
  marks: Partial<Record<string, Mark>>;
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
    const typedHere = own && !compact && IN_PLACE.has(field.holds);
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
          {SIGNS.has(field.holds) ? (
            filled && marks[field.holds] ? (
              <SignatureMark mark={marks[field.holds] as Mark} width={style.width} height={style.height} />
            ) : (
              <span className={styles.sign}>{field.holds === "initials" ? "Initial" : "Sign"}</span>
            )
          ) : null}
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

/**
 * A field's input. On a small screen: a compact dialog, its place in the guide ("2 of 5"), Save and
 * next. On a computer: a small panel beside the box (a date's calendar, a list).
 */
function Editor({
  field,
  value,
  compact,
  position,
  error,
  onCancel,
  onSave,
}: {
  field: SignerField;
  value: string;
  compact: boolean;
  position: string | null; // "2 of 5" when the field is one the guide visits
  error: string | undefined;
  onCancel: () => void;
  onSave: (value: string, andNext: boolean) => void;
}) {
  const [draft, setDraft] = useState(value);
  const input = <FieldInput field={field} value={draft} onChange={setDraft} error={error || undefined} inlineDate />;
  if (compact) {
    return (
      <Dialog
        title={field.label}
        onClose={onCancel}
        actions={
          <>
            <Button onClick={() => onSave(draft, true)}>{position ? "Save and next" : "Save"}</Button>
            <TextButton onClick={onCancel}>Cancel</TextButton>
          </>
        }
      >
        {position ? <span className={styles.position}>{`Field ${position}`}</span> : null}
        <form
          className={styles.editorForm}
          onSubmit={(event) => {
            event.preventDefault();
            onSave(draft, true);
          }}
        >
          {input}
        </form>
      </Dialog>
    );
  }
  return (
    <Beside
      field={field}
      onCancel={onCancel}
      actions={
        <>
          <Button onClick={() => onSave(draft, false)}>Save</Button>
          <TextButton onClick={onCancel}>Cancel</TextButton>
        </>
      }
    >
      {input}
    </Beside>
  );
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

/** The person's adopted signature and initials as the page draws them. */
function marksOf(adopted: readonly Adopted[]): Partial<Record<string, Mark>> {
  const marks: Partial<Record<string, Mark>> = {};
  for (const one of adopted) {
    if (one.method === "drawn" && one.strokes) marks[one.kind] = { method: "drawn", strokes: one.strokes as [number, number][][] };
    else if (one.method === "typed" && one.text && one.font) marks[one.kind] = { method: "typed", text: one.text, font: one.font };
  }
  return marks;
}

/** "2 of 5": a field's place among those the person fills (given ones aside), or null. */
function positionOf(field: SignerField, order: readonly SignerField[]): string | null {
  const theirs = order.filter((one) => !one.locked);
  const at = theirs.indexOf(field);
  return at >= 0 ? `${at + 1} of ${theirs.length}` : null;
}
