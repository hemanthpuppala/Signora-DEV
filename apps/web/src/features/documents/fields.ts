"use client";

import { useQuery } from "@tanstack/react-query";

import type { components } from "@signora/contracts";

import { api, unwrap } from "@/shared/api/client";

import { hasWorkingCopy, processingInterval, type Version } from "./api";


export const fieldsKey = (versionId: string, status: string) => ["fields", versionId, status] as const;

/**
 * A version's fields (Phase 5 LLD §5.4, topic 6). Keyed by the version's status, so they load
 * again when it becomes ready; while fields are being found they poll like the document does, so
 * the boxes the read stage found appear before the AI finishes.
 */
export function useVersionFields(documentId: string, version: Version | undefined) {
  return useQuery({
    queryKey: fieldsKey(version?.id ?? "", version?.status ?? ""),
    enabled: version !== undefined && hasWorkingCopy(version.status),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/documents/{document_id}/versions/{version_id}/fields", {
          params: { path: { document_id: documentId, version_id: version?.id ?? "" } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.status === "detecting" ? processingInterval([version?.created_at ?? ""]) : false,
    // When the same version changes state (approved, fields found) its last fields stay on screen
    // until the new ones arrive, so the panel never blinks; another version's never stand in.
    placeholderData: (previous, previousQuery) => (previousQuery?.queryKey[1] === version?.id ? previous : undefined),
  });
}

/** What a field may hold: the contract's enum, from the API's one list (Phase 6 §1.8). */
export type Holds = components["schemas"]["FieldView"]["holds"];

/** What a field holds, in plain words: every value the API can send must have one (type-checked). */
export const HOLDS: Record<Holds, string> = {
  signature: "Signature",
  initials: "Initials",
  date_signed: "Date signed",
  party_name: "Legal name",
  full_name: "Name",
  first_name: "First name",
  last_name: "Last name",
  company: "Company",
  title: "Title",
  date_of_birth: "Date of birth",
  email: "Email",
  phone: "Phone",
  address: "Address",
  city: "City",
  state: "State",
  postal_code: "Postal code",
  country: "Country",
  url: "Website",
  tax_id: "Tax number",
  bank_account: "Bank account",
  date: "Date",
  day: "Day",
  month: "Month",
  year: "Year",
  number: "Number",
  currency: "Amount",
  amount_in_words: "Amount in words",
  percent: "Percent",
  text: "Text",
  checkbox: "Checkbox",
  choice: "Choice",
  note: "Note",
  other: "Other",
};

/**
 * How a date or a part of one is written (the server's formats, Phase 7c), shown as 9 November
 * 2026 would be: every format the API sends must have one (tested).
 */
export const FORMAT_EXAMPLES: Record<string, string> = {
  "Month D, YYYY": "November 9, 2026",
  "D Month YYYY": "9 November 2026",
  "MM/DD/YYYY": "11/09/2026 · month first",
  "DD/MM/YYYY": "09/11/2026 · day first",
  "MM/DD/YY": "11/09/26 · month first",
  "DD/MM/YY": "09/11/26 · day first",
  "YYYY-MM-DD": "2026-11-09",
  D: "9",
  Dth: "9th",
  Month: "November",
  MM: "11",
  YYYY: "2026",
  YY: "26 · after a printed 20",
};

/** The types grouped for picking (Phase 6 §4); every type is in exactly one group (tested). */
export const HOLD_GROUPS: readonly { label: string; holds: readonly Holds[] }[] = [
  { label: "Signing", holds: ["signature", "initials", "date_signed"] },
  { label: "Who they are", holds: ["party_name", "full_name", "first_name", "last_name", "company", "title", "date_of_birth"] },
  { label: "Contact", holds: ["email", "phone", "address", "city", "state", "postal_code", "country", "url"] },
  { label: "Money and numbers", holds: ["currency", "amount_in_words", "number", "percent"] },
  { label: "Dates", holds: ["date", "day", "month", "year"] },
  { label: "Private", holds: ["tax_id", "bank_account"] },
  { label: "General", holds: ["text", "checkbox", "choice", "note", "other"] },
];

/** A party as the screens need it: by id, in signing order. */
export type PartyRef = { id: string; label: string; kind: "signer" | "countersigner" };
type FilledByRef = { filled_by: "role" | "sender" | "none"; party_id: string | null };

/** The design system's party tones: signers in order, then the countersigning side (prototype 13). */
const SIGNER_TONES = ["role1", "role2", "role3"] as const;
export type Tone = (typeof SIGNER_TONES)[number] | "firm" | "sender" | "none";

export function toneOf(field: FilledByRef, parties: readonly PartyRef[]): Tone {
  if (field.filled_by === "sender") return "sender";
  if (field.filled_by === "none" || !field.party_id) return "none";
  const party = parties.find((candidate) => candidate.id === field.party_id);
  if (!party) return "none";
  if (party.kind === "countersigner") return "firm";
  const signers = parties.filter((candidate) => candidate.kind === "signer");
  return SIGNER_TONES[signers.indexOf(party) % SIGNER_TONES.length] ?? "role1";
}

/** Who fills a field, in words: the party's label, before sending, or nobody. */
export function whoFills(field: FilledByRef, parties: readonly PartyRef[]): string {
  if (field.filled_by === "sender") return "Filled in before sending";
  if (field.filled_by === "none" || !field.party_id) return "Not asked";
  return parties.find((party) => party.id === field.party_id)?.label ?? "Not asked";
}

/** A signature or initials is drawn dashed (prototype 13's legend). */
export function isMark(holds: string): boolean {
  return holds === "signature" || holds === "initials";
}

// Types as the typed client returns them (it gives the API's 4-number tuples back as arrays).
export type VersionFields = NonNullable<ReturnType<typeof useVersionFields>["data"]>;
export type FieldView = VersionFields["fields"][number];
export type RoleView = VersionFields["roles"][number];
export type PendingField = VersionFields["pending"][number];
export type PlacementView = FieldView["placements"][number];
