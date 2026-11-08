import type { Status } from "@/shared/ui";

import type { VersionStatus } from "./api";

/** How a version's state reads, in plain words, with the status dot it uses. */
export const VERSION_STATUS: Record<VersionStatus, { pill: Status; label: string }> = {
  processing: { pill: "pending", label: "Processing" },
  needs_password: { pill: "viewed", label: "Needs password" },
  needs_ocr: { pill: "expired", label: "Scanned pages" },
  failed: { pill: "declined", label: "Failed" },
  processed: { pill: "completed", label: "Ready" },
};
