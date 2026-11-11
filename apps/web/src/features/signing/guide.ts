import { askedFields } from "@/shared/document/conditions";

import type { SignerField } from "./api";

/** Placed by a tap (Phase 8 §5.3), not typed. */
export const SIGNS = new Set(["signature", "initials"]);
/** Filled at submit with the time of signing (§5.6): never guided, never typed. */
export const SIGNING_DATE = "date_signed";

/** What the person's own field holds now: what was given before signing, else their draft. */
export function ownValue(field: SignerField, drafts: Readonly<Record<string, string>>): string {
  return field.locked ? (field.value ?? "") : (drafts[field.id] ?? "");
}

/** Every value the conditions read: everything shown, with the person's drafts over theirs. */
export function allValues(fields: readonly SignerField[], drafts: Readonly<Record<string, string>>): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of fields) {
    const value = field.mine ? ownValue(field, drafts) : field.value;
    if (value) values[field.id] = value;
  }
  return values;
}

type Place = SignerField["places"][number];
const top = (place: Place) => place.rect[1] ?? 0;
const leftEdge = (place: Place) => place.rect[0] ?? 0;

/** A field's place met first reading the document: page, then top to bottom, then left to right. */
export function firstPlace(field: SignerField): Place | undefined {
  return [...field.places].sort((a, b) => a.page - b.page || top(a) - top(b) || leftEdge(a) - leftEdge(b))[0];
}

function readingKey(field: SignerField): [number, number, number] {
  const first = firstPlace(field);
  return first ? [first.page, top(first), leftEdge(first)] : [Infinity, 0, 0];
}

/** The person's required fields that are asked, in reading order (§4.3). O(k log k). */
export function guided(fields: readonly SignerField[], drafts: Readonly<Record<string, string>>): SignerField[] {
  const asked = askedFields(fields, allValues(fields, drafts));
  return fields
    .filter((field) => field.mine && field.required && field.holds !== SIGNING_DATE && asked.has(field.id))
    .sort((a, b) => {
      const [pa, ya, xa] = readingKey(a);
      const [pb, yb, xb] = readingKey(b);
      return pa - pb || ya - yb || xa - xb;
    });
}

/** The guided fields still empty, in reading order. */
export function remaining(fields: readonly SignerField[], drafts: Readonly<Record<string, string>>): SignerField[] {
  return guided(fields, drafts).filter((field) => !ownValue(field, drafts));
}

export type GuideStep = "start" | "next" | "complete";

/** What the guide's button says (§4.3): Start before anything, Next while fields are left, then
 * Complete, which goes to the Submit block. */
export function guideStep(started: boolean, left: number): GuideStep {
  if (left === 0) return "complete";
  return started ? "next" : "start";
}

/**
 * The pointer's words for a field. A signature place says what clicking it does: before a
 * signature is adopted it opens the dialog ("Sign here"); after, one click signs ("Click to sign").
 */
export function pointerLabel(field: SignerField, adopted = false, touch = false): string {
  if (field.holds === "signature" || field.holds === "initials") {
    const noun = field.holds === "initials" ? "initial" : "sign";
    if (!adopted) return field.holds === "initials" ? "Initial here" : "Sign here";
    return `${touch ? "Tap" : "Click"} to ${noun}`;
  }
  return `Fill ${field.label}`;
}
