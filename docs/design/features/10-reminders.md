# Automatic reminders — low-level design

## 1. Problem

Each envelope carries a reminder interval (1 hour to 30 days, the department's default 24 hours) and a
maximum count (0 to 20, default 5), copied from the department at send. The sender can remind by hand,
but nothing reminds on its own: a signer who does not act hears nothing more, and a firm that set
"remind every 48 hours" is told something that does not happen. This adds the scheduled reminders the
platform design describes (FR-33, §5.5).

## 2. Functional requirements

| # | Requirement |
|---|---|
| FR-R1 | Everyone who still has to act and holds a working link (a signer who has not signed or declined; a countersigner once it is their turn) is emailed a reminder one interval after they were last emailed their link or a reminder. |
| FR-R2 | Automatic reminders stop at the envelope's maximum count (manual reminders count towards it), when the person signs or declines, when the envelope is completed, declined, cancelled or past its expiry, and never fall after the expiry. A maximum of 0 means none. |
| FR-R3 | A reminder sent within one interval of the expiry says when the link stops working (the last chance). |
| FR-R4 | A reminder by hand also moves that person's next automatic reminder one interval on, so they are never emailed twice in quick succession. |
| FR-R5 | A corrected email (a new link) and a countersigner's turn start the person's schedule afresh; a corrected email also starts its count again. |
| FR-R6 | Each automatic reminder is on the envelope's timeline as the system's, with how many were reminded. |
| FR-R7 | The envelope page shows each person's next reminder. |
| FR-R8 | No reminder is sent twice: two workers, a retried job or a reminder by hand at the same moment still send one email per reminder count. |

## 3. Non-functional requirements

| # | Requirement |
|---|---|
| NFR-R1 | A sweep finds due people by an index range on `next_reminder_at`, O(log N + due), never a scan of all recipients. |
| NFR-R2 | A reminder goes out within 5 minutes of being due. |
| NFR-R3 | One envelope that cannot be reminded (its data broken) never stops the others; it is logged and tried again on the next sweep. |
| NFR-R4 | Envelopes already out when this ships are scheduled one interval from the deploy, not all at once. |

## 4. Business logic

- **The schedule lives on the recipient:** `next_reminder_at`, set in one place (`schedule.schedule_next`)
  whenever the person is emailed their link or a reminder:
  `now + interval` while `reminders_sent < max_reminders` and `now + interval < expires_at`; otherwise
  NULL (no more reminders).
- **Set by:** the send (the people emailed first), every signer signing (the countersigners whose turn
  begins), a corrected email (the new link), and every reminder (by hand or automatic). A resend of the
  same link is a delivery retry and leaves the schedule as it is.
- **Due:** `next_reminder_at <= now`, the person still to act (`sent`, `opened`, `viewed`) with a working
  link, the envelope open (`sent`, `opened`, `viewed`, `signed`) and before its expiry, and under the
  maximum. A due row failing any of these is cleared (set NULL) by the sweep, so the index holds only live
  schedules; signing, declining and cancelling therefore need no extra write.
- **Concurrency:** each envelope is reminded in its own transaction under the envelope's row lock, the
  same lock the manual reminder takes, and the condition is checked again under it. The email's dedupe
  key `sign_reminder:{recipient}:{link_version}:{count}` is shared with the manual reminder, so a race sends one email.
- **Urgent:** a reminder is the last chance when `expires_at − now ≤ interval`; its subject and heading
  give the moment the link stops working.

## 5. Architecture decision (ADR-R1)

- **Context:** the worker already enqueues recurring sweeps once per time slot across workers
  (`RecurringJob`); reminders need a clock.
- **Decision:** a recurring job `envelopes.remind_due` every 5 minutes, inside the envelopes module
  (it owns the tables, the emails and the manual reminder). The reminding itself is the manual
  reminder's code (`service._remind`), so both send the same email, count and schedule the same way.
- **Rejected:** computing due people from `sent_at` and the count at sweep time (no index can serve
  it; the schedule would be re-derived in two places); a job per reminder enqueued at send (every
  change of email, turn or cancel would have to find and move it).
- **Consequences:** one column update at each moment a person is emailed; a partial index of live
  schedules.

## 6. Data design

- Migration 0034: `ix_envelope_recipients_next_reminder_at` on `envelope_recipients (next_reminder_at)
  WHERE next_reminder_at IS NOT NULL`; backfill of people still to act on open envelopes to
  `now + interval` (NFR-R4), under the same conditions as `schedule_next`.
- `RecipientView.next_reminder_at` (read-only) for the envelope page.

## 7. Algorithm and complexity

- Sweep: one `UPDATE … WHERE next_reminder_at <= now() AND NOT live` (index range over due rows), then
  up to 100 envelopes of due rows by the index, each reminded in its own transaction; repeated while a
  batch is full. O(log N + D) for D due people; constant work per reminder (one email row, one update,
  one audit event).

## 8. Interfaces

- `schedule.schedule_next(session, recipient_ids) -> None`
- `reminders.remind_due(database) -> int` (how many people were reminded); job kind `envelopes.remind_due`.
- `service.remind_automatically(uow, envelope_id) -> int`
- `emails.sign_reminder(..., last_chance: bool)`

## 9. Test strategy

- Due people are reminded once; the count, the next time and the timeline move (FR-R1, FR-R6).
- None after the maximum, after signing or declining, on a cancelled or expired envelope, or for a
  countersigner before their turn; due rows that cannot be reminded are cleared (FR-R2).
- The last-chance wording within an interval of the expiry (FR-R3).
- A manual reminder moves the next automatic one (FR-R4); a corrected email and a countersigner's turn
  schedule them (FR-R5).
- Two sweeps at once send one email each (FR-R8).
- Migration 0034 backfills two or more rows per case and leaves closed ones alone (NFR-R4).
- The envelope page shows the next reminder (FR-R7).

## Task tracker

| # | Task | Status | Evidence of completion |
|---|------|--------|------------------------|
| 1 | Schedule on send, turn, corrected email and reminder; index and backfill (0034) | done | commit f512697; `test_reminders.py` (7), `test_data_migrations.py::test_0034_…` |
| 2 | The sweep job and the shared reminder; last-chance wording | done | commit f512697; `reminders.py`, `service._remind`; `test_reminders.py` |
| 3 | Next reminder on the envelope page | done | commit 31e6650; `envelopes.test.tsx` |
| 4 | Full gate, live check | in-progress | gate: 1,088 API and 388 web tests, lint, types, imports, build, contracts (commit 31e6650); live check after deploy |

Deviation: tasks 1 and 2 share one commit, since the manual and automatic reminders were made one
code path (`service._remind`) in the same change.
