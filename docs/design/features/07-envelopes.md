# Phase 7 — Envelopes and sending (LLD)

Parent design: [`../signora-platform.md`](../signora-platform.md) · Previous: [`06-review.md`](06-review.md) ·
Branch: `phase-7/envelopes` · Prototype screens: 14 (new envelope), 07 (envelopes list), 16 (envelope detail),
the signer's email (`sign-email`).

## Problem

A version can now be reviewed and approved (Phase 6), but nothing leaves the building. Phase 7 sends an approved
document to the people who sign it: a short form asks only what the document needs from the sender, every signer gets
a clean email with their own link, and the sender can follow, remind, correct and cancel each send. Signing itself
(the signer's screen) is Phase 8; countersigning and the completed copy are Phase 9; scheduled reminders and expiry are
Phase 10. This phase lays the envelope down so those phases only add behaviour.

## Topics

| # | Topic | Status |
|---|---|---|
| 1 | What an envelope is, and its life | owner decisions 2026-11-09 |
| 2 | The send form: what is asked, and how it prefills | owner decisions 2026-11-09 |
| 3 | Who signs when, and who sees what (decided now, built in Phases 8–9) | owner decisions 2026-11-09 |
| 4 | Per-envelope settings | owner decisions 2026-11-09 |
| 5 | The signer's email and the signing link | owner decisions 2026-11-09 |
| 6 | Following a send: list, envelope page, remind, resend, change email, cancel | from the platform design |
| 7 | Low-level design (§8–§14) | proposed |

---

## 1. What an envelope is (owner decisions, 2026-11-09)

- **One envelope carries one document**: one approved version, pinned when sent. A later version, approved or not,
  never changes a send already out. (The platform design allowed several documents per envelope; superseded.)
- **Only an approved version can be sent** (platform FR-16). The current version is offered first; any approved
  version can be chosen.
- **Anyone with edit access** to the document's department sends (owners, editors, people granted edit access).
- **No drafts** (recommendation, see §15): the send form is one page; leaving it discards it. The prototype's
  "Save draft" is left out.
- **Bulk sending** (one envelope per spreadsheet row, platform FR-19) is deferred to the "later" list with Presidio
  PII redaction.
- **Additional signers** beyond the document's parties (platform FR-18, an added signature page) are deferred: the
  parties are the ones review approved.

### 1.1 States (platform §5.1, narrowed to one document)

```
sent ─any signer opened─► opened ─any signer reached the end─► viewed ─every signer signed─► signed
     ─every countersigner signed (or none)─► completed
any non-terminal ─decline─► declined │ ─expiry─► expired │ ─cancel─► cancelled
```

Phase 7 creates envelopes in `sent` and can move them to `cancelled`; every other transition belongs to the phase
that causes it (Phase 8 opens, views and signs; Phase 9 completes; Phase 10 expires). The columns and checks for all
states are created now, so later phases add transitions, not migrations.

A recipient: `waiting` (a countersigner before every signer has signed) → `sent` → `opened` → `viewed` → `signed`, or
`declined`. Terminal envelope states revoke every link.

## 2. The send form (owner decisions, 2026-11-09)

The form asks only what the document needs from the sender, generated from the approved version's parties and fields
(nothing is typed about the document itself):

- **Each signer** (signer parties, including Other kinds such as "Witness", in signing order): **name** and **email**.
  The name prefills that party's name fields in the document (`full_name`; `party_name`; `first_name` and
  `last_name`, when the document has them, are asked as First name and Last name instead of one Name). The email
  prefills the party's `email` field. Everything else of theirs (address, title, company, their signature…) the
  signer fills in Phase 8.
- **Each countersigner party**: a colleague, defaulting to the department's countersigners in order (Phase 3 §4.1),
  changeable to any active member of the company. A department with an empty list asks the sender to choose.
- **Before sending**: every field review marked "Filled in before sending" (the effective date, the governing law
  state…), each with an input for its type (a date picker for a date, a choice's options, a checkbox). Required ones
  must be filled to send; a field whose condition is not met is not asked.
- **Settings** (§4), folded under one line with their defaults showing.
- **The document**, beside the form, in the same PDF viewer: the box of the field being filled is highlighted and
  brought into view, so the sender sees where each value lands.

Prefilled values are **not editable by the signer** (owner decision: DocuSign's default); the email never is. More
can be asked of the sender later by marking more fields "Filled in before sending" in review, with no change here.

## 3. Who signs when, and who sees what (owner decisions, 2026-11-09; built in Phases 8–9)

Decided now because the envelope's data must support it:

- **Signers are emailed together** when the envelope is sent and sign separately, in any order.
- **Countersigners are emailed only once every signer has signed**, never at the same time as the signers.
- **A signer sees what earlier signers submitted**: their signatures, initials, names and signing dates, drawn in
  place, read-only. Two signers with the page open at once see each other's submission after a reload. Private
  values (tax number, bank account, date of birth, and Other types marked private) are seen only by the person who
  gave them.
- **Signers never see the countersigners' signatures** until the envelope is completed; the completed copy shows
  everything.
- **Consent twice** (ESIGN practice, as DocuSign and Adobe): once on opening (one tap to agree to sign
  electronically), and at the end a checkbox ("I've reviewed this document and this is my signature") with Submit,
  enabled when every required field is done.
- **The signer's screen** (phones included): the same PDF viewer, their fields softly highlighted, a Next button that
  moves to the next field to fill, smooth and subtle transitions (none when the person asks for reduced motion).

## 4. Per-envelope settings (owner decisions, 2026-11-09)

| Setting | Default | Allowed | From |
|---|---|---|---|
| Require email code | on | on or off | moved here from the document (2026-11-09) |
| Remind every | the department's (24 hours) | 1 hour – 30 days | Phase 3 §3 |
| Max reminders | the department's (5) | 0 – 20 | Phase 3 §3 |
| Expires after | the department's (14 days) | 1 – 365 days | Phase 3 §3 |
| Also notify | the department's list | up to 5 emails | Phase 3 §3 |

Each envelope keeps its own copy: changing the department later never changes a send already out (Phase 3 §3.2).
The document's old `require_email_code` column and its PATCH field are removed in this phase's migration.

## 5. The signer's email and the link (owner decisions, 2026-11-09)

- **Clean and premium**: the shared email layout (Phase 2), black and white, one heading, two short lines, one button:
  > **Hale & Ward LLP asks you to sign the Mutual NDA**
  > Hi Maya, Rosa Hale sent you this to review and sign. It takes a few minutes.
  > **[ Review and sign ]**
  > Or copy this link: `https://…/s/…`
  > This link is for you only. It expires on Nov 23, 2026. Questions? Reply to this email.
- **No copy button in the email**: email apps run no scripts, so a button cannot copy. The link is printed under the
  button where it can be selected and copied; the envelope page has **Copy signing link** for each person.
- **Reply-To** is the sender, so a question reaches a person.
- **Transport**: Mailpit until the owner's Gmail SMTP is ready (app password in `.env`, never shared); then
  `EMAIL_PROVIDER=smtp`. Nothing else changes.

## 6. Following a send (platform FR-20, FR-21, FR-34)

- **Envelopes** on the department page (a tab beside Documents): document, recipients, status, sent; filtered by
  status. Read-only members see none (platform §5.6: envelopes hold clients' details).
- **The envelope page**: an action bar (status, expiry; Remind now, Cancel envelope); the recipients (name, email,
  party, status, when, Copy signing link, Resend, Change email); a notice for any email not delivered, with Retry; the
  document as sent, with the sender's values in place; the timeline (from the audit chain).
- **Remind now** emails everyone who still has to act (signers now; countersigners once it is their turn).
- **Resend** emails one person their link again.
- **Change email** (a mistyped address): the old link stops working, a new one is emailed.
- **Cancel envelope**: confirmed, then every link stops working; the signers already emailed are told it was
  withdrawn.

---

# Low-level design

## 8. Requirements

### 8.1 Functional

| ID | Requirement |
|---|---|
| FR-E1 | A person with edit access sends one approved version of a document to its parties (§1, §2). |
| FR-E2 | The send form is generated from the version: signers' name and email, countersigners from the department's list, the "Filled in before sending" fields by type, the settings (§2, §4). |
| FR-E3 | Sending pins the version, stores the sender's values and the prefilled names and emails as the envelope's field values, creates the recipients, and emails every signer their link in the same transaction (the email is queued, §8.2). |
| FR-E4 | Countersigners are created waiting; nothing is sent to them in this phase (Phase 9 emails them when every signer has signed). |
| FR-E5 | Each recipient has a private signing link; it can be shown again (Copy signing link) without changing it, and stops working on change of email or a terminal state (§11.2). |
| FR-E6 | The signer's email: heading, two lines, a button, the plain link, expiry, Reply-To the sender (§5). |
| FR-E7 | Envelopes list per department, filtered by status; the envelope page with recipients, delivery state, document, timeline (§6). |
| FR-E8 | Remind now, resend, change email, cancel, retry a failed email; each audited (§6). |
| FR-E9 | Settings per envelope with the department's defaults; the document's `require_email_code` removed (§4). |
| FR-E10 | Read-only members see no envelopes; other companies get 404. |

### 8.2 Non-functional

| ID | Requirement | Threshold |
|---|---|---|
| NFR-E1 | Send latency | < 500 ms for 20 parties and 200 sender fields (emails are queued, not sent in the request) |
| NFR-E2 | Exactly one envelope per send | a retried send (same `Idempotency-Key`) returns the first envelope; no duplicate emails (dedupe keys) |
| NFR-E3 | Link secrecy | 256-bit link secret; nothing in the database lets anyone rebuild a link; compared in constant time |
| NFR-E4 | Email never blocks | an email failure never rolls back a send; it shows on the envelope with Retry (platform FR-37) |
| NFR-E5 | Pinned content | an envelope's version, values and settings never change after sending (database checks) |
| NFR-E6 | List | 1 000 envelopes in a department list in < 200 ms (indexed, paged by 50) |
| NFR-E7 | Auditability | every send, remind, resend, email change, cancel and retry on the company's audit chain |

## 9. Data design (migration `0019_envelopes`, owned by a new `envelopes` module)

```sql
envelopes
  id                       uuid PK, workspace_id uuid NOT NULL
  department_id            uuid NOT NULL       -- FK (department_id, workspace_id) → departments
  document_id              uuid NOT NULL       -- FK (document_id, workspace_id) → documents
  version_id               uuid NOT NULL       -- FK (version_id, document_id) → document_versions (same document)
  title                    text NOT NULL       -- "Mutual NDA · Maya Chen" by default, editable (1–120)
  status                   text NOT NULL       -- sent | opened | viewed | signed | completed | declined | expired | cancelled
  require_email_code       boolean NOT NULL
  reminder_interval_hours  int NOT NULL CHECK (1..720)
  max_reminders            int NOT NULL CHECK (0..20)
  expires_at               timestamptz NOT NULL
  notify_emails            text[] NOT NULL CHECK (cardinality <= 5)
  sent_by                  uuid NOT NULL, sent_at timestamptz NOT NULL DEFAULT now()
  completed_at, cancelled_at timestamptz, cancelled_by uuid
  CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL))
  INDEX (workspace_id, department_id, status, sent_at DESC)

envelope_recipients
  id                uuid PK, workspace_id, envelope_id   -- FK (envelope_id, workspace_id)
  party_id          uuid NOT NULL       -- the version's party (version_roles.id); unique per envelope
  kind              text NOT NULL       -- signer | countersigner
  stage             int  NOT NULL       -- 1 signers, 2 countersigners
  name              text NOT NULL, email citext NOT NULL
  user_id           uuid                -- countersigners: the colleague; NULL for signers
  status            text NOT NULL       -- waiting | sent | opened | viewed | signed | declined
  link_version      int  NOT NULL DEFAULT 1   -- +1 revokes every earlier link (§11.2)
  revoked_at        timestamptz         -- set on terminal envelope states
  reminders_sent    int NOT NULL DEFAULT 0, next_reminder_at timestamptz   -- Phase 10 schedules
  sent_at, opened_at, viewed_at, signed_at timestamptz
  CHECK ((kind = 'countersigner') = (user_id IS NOT NULL))
  CHECK (kind = 'signer' AND stage = 1 OR kind = 'countersigner' AND stage = 2)
  UNIQUE (envelope_id, party_id)

envelope_values
  envelope_id, workspace_id, field_id uuid    -- the version's field (version_fields.id)
  value       text                            -- text form; a checkbox "true"/"false", a choice its option value
  given_by    text NOT NULL                   -- sender | recipient (Phase 8) ; prefilled names are 'sender'
  recipient_id uuid                           -- who gave it, for recipient values
  given_at    timestamptz NOT NULL DEFAULT now()
  PRIMARY KEY (envelope_id, field_id)
```

- **Pinned content (NFR-E5)**: a trigger refuses any change to an envelope's `version_id`, document, department and
  settings, and to the sender's rows of `envelope_values`, once it exists. Only the title can still change (a
  rename). The version itself is already immutable once approved (Phase 6 trigger).
- **Version must be approved**: checked in the transaction under the version's row lock (`FOR SHARE`).
- **`documents.require_email_code`** is dropped (with its audit action kept in history).
- **Email delivery** reuses `email_messages` (Phase 2) with new categories and dedupe keys (§11.4); no new table.
- **Timeline** reads the company audit chain for subject `envelope:{id}` (Phase 1 `audit_events`); no new table.

## 10. Interface contracts (`/api/v1`)

| Method and path | What | Notes |
|---|---|---|
| `GET /documents/{d}/versions/{v}/send-form` | the generated form: signers (`party_id`, label, asks `name` or `first_name`+`last_name`, `email`), countersigners (`party_id`, label, default `user_id`, choices), sender fields (`field_id`, label, holds, required, options, condition), settings with defaults | `409 version-not-approved`; edit access |
| `POST /documents/{d}/envelopes` | send: `{version_id, title?, signers: [{party_id, name, email}], countersigners: [{party_id, user_id}], values: [{field_id, value}], settings}` → `201 Envelope` | `Idempotency-Key`; `422` naming each item; `409 version-not-approved`, `document-archived` |
| `GET /departments/{dep}/envelopes?status=&cursor=` | list, newest first, 50 a page | edit access |
| `GET /envelopes/{e}` | envelope, recipients (with delivery state of their last email), values, timeline | edit access |
| `GET /envelopes/{e}/recipients/{r}/link` | the signing link (Copy signing link) | audited as `envelope.link_copied` |
| `POST /envelopes/{e}/remind` | email everyone who still has to act | `Idempotency-Key`; `409 envelope-closed` |
| `POST /envelopes/{e}/recipients/{r}/resend` | email this person their link again | `Idempotency-Key` |
| `PATCH /envelopes/{e}/recipients/{r}` | `{email}` (and `name` while not opened): new link, old one revoked, emailed | `409 recipient-signed` |
| `POST /envelopes/{e}/cancel` | cancel: links revoked, signers already emailed told | guarded, repeat-safe |
| `POST /emails/{id}/retry` | queue a failed email again | Phase 2 delivery record |

`PATCH /documents/{d}` stops accepting `require_email_code` (422 as an unknown field).

### 10.1 Validation (`422`, each error naming its item)

- Signers: every signer party exactly once; name 1–120 (first and last 1–60 each when asked); email valid
  (the shared `normalize_email`, Phase 2).
- The same email on two parties is refused unless they are the same person by intent: one person holding two
  parties is allowed only when `confirm_same_person` lists both (§15 open question; default refuse).
- Countersigners: every countersigner party exactly once; an active member of the company.
- Values: every required, asked sender field (condition met); each value valid for its type (§11.3); unknown fields
  refused.
- Settings within the department's ranges (§4); title 1–120.

## 11. Algorithms and complexity

R parties, F fields, V sender values.

| Step | Approach | Cost |
|---|---|---|
| Send form | one read of the version's parties and fields (review's `read_set`), group by `filled_by`; conditions resolved against the chosen options | O(R + F) |
| Validate a send | maps by party and field id, one pass; type checks per value (§11.3) | O(R + V) |
| Prefill | for each signer party, the party's name/email fields by `holds` from an index built once | O(R + F) |
| Write | one multi-row insert each for recipients and values, one per email (constant number of statements) | O(R + V) |
| List | index range on `(workspace, department, status, sent_at)`, keyset paging | O(log N + 50) |

### 11.1 Countersigner defaults

The k-th countersigner party (by signing position) gets the department's k-th countersigner; parties beyond the
list's length are left for the sender to choose. O(R).

### 11.2 Signing links (ADR-E1)

- **Context**: a link must be shown again (Copy signing link, resend) without changing it, revoked on change of email,
  and never rebuildable from the database (NFR-E3). Storing only `sha256(token)` (platform §9) cannot show a link
  again; storing the token, even encrypted, puts every live link in the database.
- **Decision**: the link carries `recipient_id`, `link_version` and `HMAC-SHA256(SIGNING_LINK_SECRET, recipient_id ‖
  link_version)`, base64url: `/s/{token}`. Showing it again recomputes it; checking it recomputes and compares in
  constant time, then requires `link_version` to equal the row's and the recipient not revoked. Change of email
  increments `link_version`, revoking every earlier link. The secret lives in `.env` only (new
  `SIGNING_LINK_SECRET`, 32 bytes, required in production).
- **Consequences**: O(1) lookup by the id in the token, no token table, no stored secret per link; rotating the secret
  revokes every outstanding link (documented). Phase 8 exchanges the link for a short session cookie and a token-free
  URL (platform §9).

### 11.3 Value formats (shared with Phase 8)

One pure module, `review.formats` (review owns the field types): `validate(holds, value, options) -> str | error` for
every type in the manual layer: text and note (1–2 000), email (`normalize_email`), phone (7–20 digits after
stripping), date (ISO `YYYY-MM-DD`), number/currency/percent (decimal; percent 0–100), checkbox (`true`/`false`),
choice (one of its option values), URL (`https://` only), and the private types as text. The send form and the
signer's submit (Phase 8) both call it, so a value is judged once, the same way. O(1) per value.

### 11.4 Emails

`notifications.send_email` (Phase 2) with categories `sign_request`, `sign_reminder`, `sign_withdrawn`; dedupe keys
`sign_request:{recipient}:{link_version}`, `sign_reminder:{recipient}:{reminders_sent}`, `sign_withdrawn:{recipient}`;
a deterministic `Message-ID` from the record id (platform §5.7). Reply-To the sender (a transport change: both
transports set the header).

## 12. Module layout

```
apps/api/src/signora/modules/envelopes/
  __init__.py     public: router; send_form, read_envelope (for Phase 8–9)
  models.py       envelopes, envelope_recipients, envelope_values
  form.py         the generated send form (pure over review's set)
  links.py        ADR-E1: make and check a link (pure, the secret passed in)
  service.py      send, remind, resend, change email, cancel: transactions, locks, audit, emails
  emails.py       the three emails' words (the shared layout)
  routes.py       §10
apps/api/src/signora/modules/review/formats.py   §11.3 (pure, public submodule)
```

Dependencies: envelopes → review (read the version's set, formats) → documents (approved version, archived) and
departments (settings, countersigners), notifications, audit, identity_access. Nothing imports envelopes yet; Phase 8's
`signing` module will (import contracts added).

Web: `features/envelopes/` — `SendPage` (`/departments/{id}/documents/{documentId}/send`), `EnvelopesTab` on the
department page, `EnvelopePage` (`/departments/{id}/envelopes/{envelopeId}`); the send form's inputs by type in
`features/envelopes/inputs.tsx` (reused by Phase 8's signer screen, so they live where both can import them:
`shared/ui` for the plain inputs, the per-type mapping in one module).

## 13. Screens

- **Document page**: on an approved version the action bar gains **Send for signature** (primary). A version in
  review shows why it can't be sent ("Approve it to send").
- **Send page**: action bar "Send Mutual NDA · version 3" with **Send** (disabled until valid); left, the PDF with the
  field being filled highlighted; right, sections with the design system's titles and "?" help: **Who signs** (per
  signer: Name, Email), **Countersigns** (per firm party: a colleague), **Before sending** (by type), **Settings**
  (folded: "Email code on · reminds every 24 hours, up to 5 · expires in 14 days"), **Title**. Errors name the field
  and bring it into view.
- **Envelopes tab** (department page): a table (Document · Recipients · Status · Sent) with status chips; a row opens
  the envelope.
- **Envelope page**: action bar (title, status, "expires Nov 23"; Remind now, Cancel envelope); **Recipients** (rows:
  name and email, party, status with time, Copy signing link, Resend, Change email via the pencil); **Email not
  delivered** notice with Retry; **Document** (the PDF as sent, sender values drawn in their boxes); **Timeline**.
- **The email** (§5), checked in Mailpit's HTML and text views.

## 14. Tests

Backend (Postgres):
- Send form: signers, countersigners (defaults in order; empty list), sender fields by type and condition; a version
  in review refused.
- Send: envelope, recipients, values, prefilled names and emails, pinned version; signers' emails queued, none to
  countersigners; audit; idempotent replay; every 422 rule; archived document and unapproved version refused;
  read-only refused; another company 404.
- Links: made and checked; a wrong HMAC, an old `link_version`, a revoked recipient refused; showing again gives the
  same link; constant-time compare (uses `hmac.compare_digest`).
- Remind, resend, change email (old link dead, new emailed), cancel (links dead, withdrawn emails), retry; each
  audited; closed envelopes refused.
- Formats: one case per type, valid and invalid.
- Migration: `documents.require_email_code` dropped (and restored on downgrade); new tables' checks.
- NFR-E1 timing: 20 parties and 200 values sent in < 500 ms.

Web (Vitest): send page (generated sections, inputs by type, validation, highlight follows the field, send with an
idempotency key); envelopes tab; envelope page (copy link, resend, change email, cancel with confirmation, retry);
"Send for signature" only on approved versions.

Live: send the reviewed NDA to two test signers and a countersigner colleague; the emails in Mailpit (HTML and text,
link copyable); copy link; change an email; cancel.

## 15. Open questions (recommendations in place until the owner decides)

1. **Drafts**: none (one-page form). The prototype's "Save draft" left out.
2. **One person on two parties** (the same email twice): refused by default, allowed after a confirmation naming both.
3. **Prefilling `party_name` (legal name) from the person's name**: when a party is a company, its legal name is not
   the person's. Recommendation: prefill `full_name`/first/last from the name; prefill `party_name` only when the
   party has no `company` field, otherwise leave it for the signer.
4. **Title**: "{document} · {first signer's name}", editable on the send page.
5. **Withdrawn email on cancel**: sent to signers who were emailed and have not signed (recommended), or none.

## 16. Task tracker

| # | Task | Status | Evidence |
|---|---|---|---|
| 7.1 | This design, owner decisions §1–§6, open questions §15 answered | in progress | this document |
| 7.2 | Migration 0019 (envelopes, recipients, values; drop `documents.require_email_code`); models; triggers | todo | — |
| 7.3 | `review.formats` (§11.3) | todo | — |
| 7.4 | Links (ADR-E1), `SIGNING_LINK_SECRET` | todo | — |
| 7.5 | Send form (§2, §11.1) | todo | — |
| 7.6 | Send: validation, prefill, values, recipients, emails, audit, idempotency | todo | — |
| 7.7 | Remind, resend, change email, cancel, retry | todo | — |
| 7.8 | List and envelope read (timeline, delivery state) | todo | — |
| 7.9 | Emails: words, Reply-To, Message-ID, Mailpit check | todo | — |
| 7.10 | Web: Send for signature, send page (inputs by type, highlight), settings | todo | — |
| 7.11 | Web: envelopes tab, envelope page (copy link, resend, change email, cancel, retry, timeline) | todo | — |
| 7.12 | Web: remove the document's email-code remnants; contract | todo | — |
| 7.13 | Live check, deploy, PR | todo | — |
