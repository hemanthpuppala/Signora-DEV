"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/shared/api/client";

import { processingInterval, type Version } from "./api";


export const fieldsKey = (versionId: string, status: string) => ["fields", versionId, status] as const;

/**
 * A version's fields (Phase 5 LLD §5.4, topic 6). Keyed by the version's status, so they load
 * again when it becomes ready; while fields are being found they poll like the document does, so
 * the boxes the read stage found appear before the AI finishes.
 */
export function useVersionFields(documentId: string, version: Version | undefined) {
  return useQuery({
    queryKey: fieldsKey(version?.id ?? "", version?.status ?? ""),
    enabled: version !== undefined && (version.status === "detecting" || version.status === "ready"),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/documents/{document_id}/versions/{version_id}/fields", {
          params: { path: { document_id: documentId, version_id: version?.id ?? "" } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.status === "detecting" ? processingInterval([version?.created_at ?? ""]) : false,
  });
}

/** What a field holds, in plain words. */
export const HOLDS: Record<string, string> = {
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
  tax_id: "Tax number",
  bank_account: "Bank account",
  date: "Date",
  number: "Number",
  currency: "Amount",
  amount_in_words: "Amount in words",
  percent: "Percent",
  text: "Text",
  checkbox: "Checkbox",
  choice: "Choice",
};

/** The design system's party tones: signers in order, then the countersigning side (prototype 13). */
const SIGNER_TONES = ["role1", "role2", "role3"] as const;
export type Tone = (typeof SIGNER_TONES)[number] | "firm" | "sender" | "none";

export function toneOf(field: Pick<FieldView, "filled_by" | "role">, roles: readonly RoleView[]): Tone {
  if (field.filled_by === "sender") return "sender";
  if (field.filled_by === "none" || !field.role) return "none";
  const role = roles.find((candidate) => candidate.slug === field.role);
  if (!role) return "none";
  if (role.kind === "countersigner") return "firm";
  const signers = roles.filter((candidate) => candidate.kind === "signer");
  return SIGNER_TONES[signers.indexOf(role) % SIGNER_TONES.length] ?? "role1";
}

/** Who fills a field, in words: the party's label, before sending, or nobody. */
export function whoFills(field: Pick<FieldView, "filled_by" | "role">, roles: readonly RoleView[]): string {
  if (field.filled_by === "sender") return "Filled in before sending";
  if (field.filled_by === "none" || !field.role) return "Not asked";
  return roles.find((role) => role.slug === field.role)?.label ?? field.role;
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
