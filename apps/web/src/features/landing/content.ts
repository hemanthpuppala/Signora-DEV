/** The landing page's sample content, shared by the markup and the demos that animate it. */

export const SECTIONS = [
  { id: "templates", label: "Templates" },
  { id: "extract", label: "Extraction" },
  { id: "how", label: "Try it" },
  { id: "sign", label: "Signing" },
  { id: "firm", label: "For firms" },
] as const;

/** The fields the extraction clip finds, in the order of the row under it. */
export const FIELD_NAMES = ["Client name", "Matter", "Effective date", "Client signature"] as const;

export const TEAMS = [
  { name: "Litigation", templates: ["Engagement Letter", "Litigation Hold", "Settlement Offer"] },
  { name: "Corporate", templates: ["NDA", "Board Consent", "Share Transfer"] },
  { name: "Real Estate", templates: ["Lease Agreement", "Purchase Offer", "Disclosure Form"] },
  { name: "HR", templates: ["Offer Letter", "Employment Contract", "Exit Agreement"] },
] as const;

/** Who acts on an envelope, left to right. */
export const LANES = ["Associate", "Signora", "Client", "Partner"] as const;

/** An envelope's record: each step and the index of the lane that acts. */
export const LANE_STEPS: readonly (readonly [label: string, lane: number])[] = [
  ["Uploaded", 0],
  ["Fields found", 1],
  ["Sent · locked", 0],
  ["Opened", 2],
  ["Signed", 2],
  ["Filed", 3],
];

export const SAMPLE_TEMPLATE = { name: "Engagement Letter.docx", size: 48230 } as const;
