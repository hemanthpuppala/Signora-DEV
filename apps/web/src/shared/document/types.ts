import type { components } from "@signora/contracts";

/**
 * What a field input needs of a field: the send form's fields and the signer's both have it, so
 * one input serves both (Phase 7 §2, Phase 8 §4.4).
 */
export type InputField = Pick<
  components["schemas"]["FormField"],
  "label" | "holds" | "holds_label" | "required" | "options" | "format"
>;

/** What the rule for conditions needs of a field (the server's envelopes.sending.asked). */
export type Conditioned = {
  id: string;
  depends_on: { field_id: string; option: string } | null;
};
