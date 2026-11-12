import { describe, expect, it } from "vitest";

import type { Envelope } from "./api";
import { draftFrom } from "./EnvelopePage";

const person = (id: string, kind: string, party: string | null, name: string, email: string, extra = {}) => ({
  id,
  kind,
  party_id: party,
  party_label: null,
  name,
  email,
  status: "sent",
  sent_at: null,
  opened_at: null,
  viewed_at: null,
  signed_at: null,
  declined_at: null,
  decline_reason: null,
  next_reminder_at: null,
  delivery: null,
  ...extra,
});

const ENVELOPE = {
  id: "e-1",
  title: "Mutual NDA · Maya Chen",
  status: "declined",
  document_id: "d-1",
  version_id: "v-1",
  sent_at: "2026-11-01T10:00:00Z",
  expires_at: "2026-11-15T10:00:00Z",
  require_email_code: true,
  reminder_interval_hours: 24,
  max_reminders: 5,
  notify_emails: ["desk@firm.example"],
  recipients: [
    person("r-1", "signer", "p-client", "Maya Chen", "maya@example.com", { status: "declined", decline_reason: "The fee is wrong" }),
    person("r-2", "countersigner", "p-firm", "Rosa Hale", "rosa@firm.example", { status: "waiting" }),
    person("r-3", "copy", null, "Records", "records@firm.example"),
  ],
  values: [
    { field_id: "f-date", value: "2026-12-01", given_by: "sender" },
    { field_id: "f-email", value: "maya@example.com", given_by: "prefill" },
    { field_id: "f-title", value: "Founder", given_by: "recipient" },
  ],
} as unknown as Envelope;

describe("send again", () => {
  it("starts from the same version, people, values and settings, and says why", () => {
    const draft = draftFrom(ENVELOPE);

    expect([draft.documentId, draft.versionId, draft.title]).toEqual(["d-1", "v-1", "Mutual NDA · Maya Chen"]);
    expect(draft.values).toEqual({ "f-date": "2026-12-01" }); // the sender's own only
    expect(draft.signers).toEqual({ "p-client": { name: "Maya Chen", email: "maya@example.com" } });
    expect(draft.countersigners).toEqual({ "p-firm": "rosa@firm.example" });
    expect(draft.copies).toEqual([{ name: "Records", email: "records@firm.example" }]);
    expect(draft.settings.expiry_days).toBe(14);
    expect(draft.note).toBe("Maya Chen declined: “The fee is wrong”");
  });
});
