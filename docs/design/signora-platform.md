# Signora — Low-Level Design

Status: draft v6 (2026-11-06) · Owner: Hemanth Puppala · Deadline: 2026-11-13 00:34 PST

**Source of truth:** where this document and a feature LLD in `docs/design/features/` disagree, the feature LLD is
authoritative and this document is corrected to match.

Changelog
- v6 (2026-11-07): aligned with the Phase 1 backbone LLD (`docs/design/features/01-backbone.md`), which is authoritative for jobs, events, idempotency, audit, storage, configuration, errors and health. Email moves from an `email_outbox` table to `email.send` jobs plus an `email_messages` delivery record owned by `notifications`; idempotency keys apply to create actions while state changes are guarded; audit entries are written synchronously (not via events) with no `prev_hash` column; carried items for Phase 2 and hardening added to the delivery plan.
- v5 (2026-11-07, PR #1 review): Gotenberg isolated on an internal-only `convert` network with outbound features disabled, reached through a `gotenberg-gateway` forwarder; compose networks split into `app` and `convert`; host-first `.env` defaults with one `*_PORT` per service shared by Docker and the app (`POSTGRES_PORT`, `GOTENBERG_HOST`/`GOTENBERG_PORT`; `*_HOST_PORT` and `GOTENBERG_URL` removed); eval tooling merged into the `dev` dependency group; installer pins uv 0.9.17 by verified archive checksum and refuses older uv; blob paths must resolve against the repo root (Phase 1 requirement).
- v4: delivery re-planned as vertical feature slices (backend + frontend per feature, LLD per feature), core first; bulk send, ID verification, OCR moved to later.
- v3: monorepo layout and modular-monolith module map with public interfaces, ownership, communication rules and tool-enforced boundaries (ADR-008).
- v2: two access levels only (read, read/write); multiple signers and countersigners with role-scoped field keys; dynamic send form and CSV template; deterministic detector as a separate, independently scored module; idempotency and failure recovery; explicit signer-transparency requirements; corrected accuracy metrics; eval harness kept private.
- v1: initial design.

---

## 1. Problem statement

Service firms (law, accounting, immigration, insurance, staffing…) must get the same client agreement(s)
signed before any work starts on a **file** (one job or case for one client). Today that is manual:
fill a Word template, email a PDF, chase, collect a scan, countersign, file it. It costs days per file.

**Signora** is a multi-tenant SaaS that turns this into: upload your agreements once → fields are detected
(deterministically and with AI) → a human approves → send to any number of customers (one by one or a
spreadsheet) → every signer signs in a minimal, secure page → optional countersign → locked PDF with a
certificate of completion goes to everyone. Department-level organization and access control let a
whole company use it.

Acceptance test (from the brief): a grader uploads an **agreement we have never seen** (the "MIND client
agreement") and gets it signed start to finish at our submission URL.

### Glossary

| Term | Meaning |
|---|---|
| Workspace | One company (tenant). All data is scoped to a workspace. |
| Project | A department folder inside a workspace (e.g. Finance, HR). Holds documents and envelopes, and owns settings (POC, reminders, countersigners, verification). |
| Document | An agreement template inside a project (e.g. "NDA"). |
| Document version | An immutable uploaded file + its detected/approved fields. Editing the file = new version. |
| Role | A party slot defined by a document version: `client_1`, `client_2`, `guarantor`, `firm`… Each role is either a **signer role** (filled by an outside person) or a **countersigner role** (filled by a workspace user). |
| Field | A logical value on a document, keyed `{role}.{attribute}` or `agreement.{attribute}`, with type, owner, required flag. |
| Placement | Where a field is drawn: page + bounding box. One field → 1..n placements. |
| Envelope | One bundle of approved document versions sent to one set of people for one file. |
| Recipient | A person on an envelope, mapped to one or more document roles. |
| POC | Point of contact per project: receives signed/declined/expired notifications. |

---

## 2. Functional requirements

### Accounts, tenancy, access
- **FR-1** A visitor can create an account (email + password, no OAuth); this creates a workspace and gives them workspace read/write. The workspace creator cannot be removed or demoted (lock-out protection).
- **FR-2** Users with workspace read/write can invite teammates by email; invitees set a password via a one-time link.
- **FR-3** Exactly two access levels: **read** and **read/write**.
  - Workspace level: read/write = create projects, manage members and project grants; implies read/write on every project.
  - Project level: a grant of read/write on a specific project. Everyone in the workspace has read on every project by default.
- **FR-4** **read** on a project shows only its documents and aggregate counts (sent / signed / pending). No envelopes, customer names, emails, or field values.
- **FR-5** **read/write** on a project shows everything and allows uploading documents, reviewing/approving fields, sending, bulk sending, and countersigning (if designated).
- **FR-6** Data of one workspace is never readable from another workspace.

### Documents & field detection
- **FR-7** Read/write users create projects with: name, description, POC email(s), reminder interval (default 24h), max reminders, expiry (default 14d), countersigner users (0..n), optional firm access code, optional ID verification.
- **FR-8** Upload PDF or DOCX (DOCX converted to PDF via Gotenberg), with a name and an optional natural-language description passed to the AI as context.
- **FR-9** Every upload creates an immutable document version identified by SHA-256; prior versions stay viewable and auditable.
- **FR-10** Two independent detectors produce fields: a **deterministic detector** (AcroForm widgets, layout rules) and an **AI detector**. Each is scored separately by the eval harness; a merge step combines them (§7).
- **FR-11** Detection infers **roles** (how many signing parties, which are customer-side vs firm-side) and assigns every field to a role or to `agreement`.
- **FR-12** Documents of any length (incl. 100+ pages) are processed (§7).
- **FR-13** Image-only / scanned PDFs are detected and flagged "needs OCR" (OCR itself is deferred, §15).
- **FR-14** A review canvas shows the PDF with fields highlighted per role (color-coded), signatures/initials visually distinct; the user can add/delete/move/resize fields, relabel, retype, change role/owner, toggle required, add/rename/remove roles, then **Approve**.
- **FR-15** On approval, the diff between detector output and approved fields is stored (§7.4).
- **FR-16** Only approved versions can be sent.

### Sending
- **FR-17** A read/write user selects ≥1 approved documents and adds recipients. The **send form is generated dynamically** from the union of the documents' roles and sender-owned fields:
  - one block per signer role, with email (required) + the person attributes that role needs (e.g. `full_name`, or `first_name` + `last_name`, `address_*`);
  - roles with the same slug across documents are merged (asked once); the user can remap roles when slugs differ (e.g. NDA "Recipient" ↔ TOS "Customer");
  - one block for `agreement.*` sender fields (fee %, effective date…);
  - countersigner roles default to the project's countersigners and can be changed to any read/write user on the project.
- **FR-18** **Additional signers:** the sender may add more signer recipients than the documents define (no upper limit). Extra signers get an auto-generated signature addendum page (name, signature, date) appended to the final PDF.
- **FR-19** Bulk send: download a CSV/XLSX template whose columns are generated from the selected documents (e.g. `client_1.email, client_1.full_name, client_2.email, …, agreement.fee_percent`), upload it, deterministic parse (no AI), per-row validation preview, background send (throttled for Gmail limits).
- **FR-20** Each recipient gets an email with their own secure link. A "Copy signing link" action exists per recipient in the console.
- **FR-21** Users can cancel an envelope, resend to one recipient, change a recipient's email (revokes that link), and trigger "remind now".

### Signing
- **FR-22** Opening a link requires a 6-digit one-time code emailed to that recipient; optionally the project access code; optionally Stripe Identity verification.
- **FR-23** The signer page is minimal: the document(s), a small "Next field" control, decline, and **Submit** at the end of the document flow (not a pinned overlay). Each signer sees and fills only their own role's fields; other roles' values are shown read-only (sender values) or as empty boxes (not yet signed).
- **FR-24** The signer explicitly sees (signer transparency):
  1. an electronic-records consent screen with the disclosure before the document (paper copy right, how to withdraw, system requirements) and an "I agree to use electronic records and signatures" checkbox;
  2. a statement at the Submit button that clicking it applies their electronic signature with intent to sign;
  3. a clear final action labelled **Sign and submit**;
  4. a confirmation screen showing the date and time of signing (with time zone) and the verification method(s) used (email code, access code, ID);
  5. a download link for their copy, and the completed copy by email.
- **FR-25** Submit is enabled only when the signer reached the end of all documents, consented, and every required field of their role validates. Signature/initials drawn or typed, with "Apply to all".
- **FR-26** Server re-validates all required fields and formats deterministically on submit (no AI).
- **FR-27** Any signer may decline with a reason; this declines the envelope for everyone.
- **FR-28** After a signer submits they get a receipt email; when the envelope completes, everyone gets the completed copy.

### Countersign, completion, notifications
- **FR-29** Signing order: all signer recipients sign in parallel; when all have signed, countersigner recipients are notified and sign in parallel.
- **FR-30** Each countersigner gets a secure link (OTP-protected) and can alternatively sign from the console. Only the designated user can sign their role. Their saved signature is applied on an explicit "Review and sign" confirmation.
- **FR-31** On completion each document is stamped and flattened, a certificate of completion page is appended (every recipient: name, email, role, verification method, timestamps, IP, user agent; original + final SHA-256), and it is emailed to all recipients, the POC, and downloadable in the console.
- **FR-32** POC and countersigners are notified when all signers have signed, on decline, and on expiry. Not on opened.
- **FR-33** Reminders go to each recipient who still has to act, every *interval*, up to max count or expiry; the last reminder before expiry uses an urgent template.
- **FR-34** Statuses exist per recipient and per envelope (§5.1). The console shows both, a timeline, and a "next reminder in …" badge.
- **FR-35** Every action is written to an append-only, hash-chained audit log.

### Reliability
- **FR-36** Repeating any state-changing request never duplicates its effect: create actions (send, upload, invite, create project, remind/resend, bulk confirm) require an `Idempotency-Key`; state changes (submit, decline, countersign, approve) are guarded updates that return their original result when repeated; jobs, webhooks and bulk rows are deduplicated. No duplicate signatures, final PDFs, certificates or emails (§5.7; backbone LLD topics 1 and 3).
- **FR-37** Email failures never roll back or block business state. Each email has a delivery record (`email_messages`, owned by `notifications`) that is retried automatically through its `email.send` job and is visible and manually retryable in the console.

---

## 3. Non-functional requirements

| ID | Area | Target |
|---|---|---|
| NFR-1 | Detection latency | ≤ 60 s p95 for a 20-page text PDF; ≤ 4 min for 150 pages. Async with progress. |
| NFR-2 | Detection quality | On the private corpus (§11): signature/initials recall ≥ 95 %, field F1 ≥ 0.85, role assignment accuracy ≥ 90 %. |
| NFR-3 | Detection cost | ≤ $0.02 per 20-page document with `gpt-6-luna` ($0.10 / $0.50 per 1M tokens in/out). |
| NFR-4 | Signer page | First render ≤ 2 s on a phone over 4G for a 10-page doc; works at 360 px width. |
| NFR-5 | Security | TLS (Funnel). Tokens ≥ 256-bit, stored hashed. Argon2id passwords. CSP, HSTS, `noindex`, `Referrer-Policy: no-referrer`. Tenant isolation enforced in the data-access layer and tested. |
| NFR-6 | Integrity | Source and final PDFs hashed (SHA-256); audit log hash chain; DB triggers forbid UPDATE/DELETE on audit rows and approved versions. |
| NFR-7 | Reliability | Exactly-once business state transitions; at-least-once email with duplicate suppression (§5.7). Restart-safe: all jobs persisted in Postgres. |
| NFR-8 | Availability | Single host (developer laptop via Tailscale Funnel), best effort. |
| NFR-9 | Email | Gmail SMTP (≈500 recipients/day). Bulk sends throttled; provider behind an interface. |
| NFR-10 | Observability | Structured JSON logs with request id and workspace id; detection metrics persisted. |
| NFR-11 | Maintainability | Modular monolith, typed (mypy strict / TS strict), lint + tests runnable by script. |

---

## 4. Architecture (ADR-001: modular monolith)

**Context.** One developer, 7 days, single host, one tenant at grading time, but must be sellable.
**Decision.** Modular monolith: one FastAPI codebase run as two processes (API, worker) sharing Postgres; a
Next.js frontend; Gotenberg as a stateless conversion sidecar; Caddy as the single entry point.
**Consequences.** `docker compose up` deploys everything; module boundaries (esp. `detection`) allow later
extraction into separate services without rewrites. No independent scaling today — acceptable.

```
Internet ──TLS──► Tailscale Funnel (hemanth.tail50655e.ts.net:443) ──► 127.0.0.1:3100
                     Caddy :3100 ── security headers, body limits
                     ├─ /api/*  → FastAPI (api)        ┐
                     └─ /*      → Next.js (web)        ├─ Postgres (data + job queue)
                     worker (same Python codebase) ────┘
                       ├─ detection jobs ─► Gotenberg (DOCX→PDF), AI provider (OpenAI-compatible)
                       ├─ reminders / expiry scheduler
                       ├─ bulk send, email.send jobs ─► Gmail SMTP
                       └─ finalize PDFs
                     Stripe Identity (test mode) ◄─ redirect + webhook
```

- **Caddy** — reverse proxy: one public port, path routing, headers, body limits.
- **Gotenberg** (`gotenberg/gotenberg:8.40.0-libreoffice`, pinned) — HTTP wrapper around LibreOffice for DOCX→PDF. It converts untrusted uploads, so it sits alone on an internal-only Docker network (`convert`, no egress) with `--api-disable-download-from`, `--webhook-disable` and `--libreoffice-deny-{private,public}-ips` as a second SSRF layer. A `gotenberg-gateway` socat forwarder publishes `127.0.0.1:${GOTENBERG_PORT}` (default 53000) for host processes; in-compose services join `convert` and call `gotenberg:3000`.
- **ADR-002: Postgres as job queue** (`SELECT … FOR UPDATE SKIP LOCKED`) instead of Redis/Celery; the `jobs` table is the transactional outbox (enqueued in the same transaction as the business write), durable across restarts. Details: backbone LLD topics 1–2.
- **ADR-003: Build signing in-house** rather than wrap DocuSign: grader finishes in one URL with no third-party accounts; product margin; ESIGN/UETA requirements are implementable (§9).
- **ADR-004: PyMuPDF** for parsing/stamping/flattening (AGPL-3.0 or Artifex commercial). Fine for a public repo; production sale needs a commercial license or a swap to `pypdfium2` + `pdfplumber` + `pypdf`. Documented in README. Note (verified 2026-11-06): `pymupdf` 2.0 hard-depends on `onnxruntime` and absorbs the former `pymupdf-layout` code (1.x was PolyForm Noncommercial; the 2.0 `pymupdf-layout` package is an empty placeholder), so the declared license is PyMuPDF's AGPL/commercial dual license.
- **ADR-005: AI provider** behind an OpenAI-compatible client (`AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`). Default `gpt-6-luna` (text+image input, structured outputs, 1.05M context). Chat Completions with `response_format: json_schema`; parse defensively (choose the schema-valid item).
- **ADR-006: Storage** behind a `BlobStore` interface; local content-addressed filesystem now, S3 later. Blobs are immutable.
- **ADR-007: Detectors as pluggable modules, not separate services (yet).** Deterministic and AI detectors implement one `Detector` interface (`detect(DocumentLayout, context) -> DetectionResult`) and are scored independently. They run in the worker today; either can be moved to its own container later without changing callers. A separate network service now would add deployment and failure surface with no scaling benefit at this volume.

### ADR-008: Monorepo + modular monolith with enforced module boundaries
**Context.** The product must stay maintainable as it grows into a sellable SaaS, and parts (detection,
notifications) may later need to scale or deploy independently.
**Decision.** One repository holding every deployable and shared contract (monorepo). The backend is one
deployable application split into **business modules**, each owning its data, logic and API, and exposing a
single public interface. Boundaries are enforced by tooling, not convention.
**Consequences.** One build, one deploy, one transaction boundary (simple consistency); each module can be read,
tested and changed alone; a module can later be extracted to a service by replacing in-process calls to its
public interface with network calls, and its event subscriptions with a broker.

#### Repository layout
```
signora/                                  (monorepo root)
├── apps/
│   ├── api/                              Python backend: one application, two entrypoints (api, worker)
│   │   ├── pyproject.toml
│   │   ├── src/signora/
│   │   │   ├── kernel/                   technical foundation, no business rules
│   │   │   │   config · db · logging · errors · security (hashing, tokens) · blobstore
│   │   │   │   jobs (queue) · events (domain-event bus over the queue) · idempotency · ratelimit · clock
│   │   │   ├── modules/                  business modules (see table below)
│   │   │   │   └── <module>/
│   │   │   │       ├── __init__.py       PUBLIC interface: facade functions, DTOs, event types — the only importable surface
│   │   │   │       ├── domain.py         entities, value objects, rules, state machines (pure Python)
│   │   │   │       ├── service.py        use cases; transactions; publishes events
│   │   │   │       ├── repository.py     persistence for this module's tables only
│   │   │   │       ├── models.py         SQLAlchemy tables owned by this module
│   │   │   │       ├── router.py         HTTP endpoints (FastAPI)
│   │   │   │       ├── schemas.py        request/response models
│   │   │   │       ├── handlers.py       subscriptions to other modules' events / job handlers
│   │   │   │       └── tests/
│   │   │   └── entrypoints/              api.py (FastAPI app factory) · worker.py (job loop) · cli.py
│   │   └── migrations/                   Alembic
│   └── web/                              Next.js frontend
│       └── src/
│           ├── app/                      routes: /(console)/…, /s/… (signer)
│           ├── features/<module>/        UI per business module, mirrors backend modules
│           └── shared/                   SSoT primitives: ui/, pdf-canvas/, signature/, api-client/
├── packages/
│   └── contracts/                        OpenAPI spec exported from the API + generated TS types (SSoT for the API contract; generated, never hand-edited)
├── infra/
│   ├── compose.yaml                      postgres, gotenberg, api, worker, web, caddy, mailpit(dev)
│   └── caddy/Caddyfile
├── docs/                                 design/, adr/, agent-memory/
├── scripts/                              dev helpers (contract generation, seed data)
├── eval/                                 PRIVATE detection eval — git-ignored
└── Makefile                              one entry point: make dev | test | lint | contracts | eval
```
Tooling: `uv` for Python, `pnpm` workspace for TypeScript (`apps/web`, `packages/contracts`).

#### Business modules
| Module | Owns (responsibility) | Owns tables | Public interface (examples) | Depends on |
|---|---|---|---|---|
| `identity_access` | accounts, sessions, workspaces, members, invites, access policy | users, sessions, workspaces, memberships, invites, project_grants | `current_actor()`, `authorize(actor, action, resource)` | kernel |
| `projects` | departments, settings, countersigner designations | projects, project_countersigners | `get_project()`, `effective_settings()` | identity_access |
| `documents` | documents, immutable versions, roles, fields, placements, review & approval, review metrics | documents, document_versions, roles, fields, placements, review_metrics | `get_approved_version()`, `field_schema(versions)` | projects |
| `detection` | normalize, layout, deterministic + AI detectors, merge, metric function | detection_results | `detect(version_id) -> DetectionResult` (job) | kernel only (receives bytes + context; no knowledge of projects) |
| `envelopes` | send form generation, envelopes, recipients, role mapping, status machine, bulk, reminders, expiry | envelopes, envelope_documents, recipients, recipient_roles, field_values, bulk_* | `create_envelopes()`, `record_signature()` | documents, projects |
| `signing` | signer-facing flow: link exchange, OTP, access code, consent, submit validation, countersign | (uses envelopes' interface; owns otp/session columns via envelopes API) | signer HTTP API | envelopes, verification |
| `verification` | Stripe Identity sessions, webhook | identity_checks | `start_check()`, `check_status()` | kernel |
| `rendering` | stamp, flatten, addendum page, certificate, hashes | — (writes blobs) | `finalize(envelope_snapshot) -> FinalDocs` | kernel only (pure input → output) |
| `notifications` | templates, email delivery records, SMTP provider, retry | email_messages | subscribes to events; `retry(email_id)` | kernel |
| `audit` | append-only hash-chained log, verification | audit_events | `record()` called synchronously inside each action's transaction; `verify()` | kernel |

Dependency graph is acyclic and points one way:
`identity_access ← projects ← documents ← envelopes ← signing`; `detection`, `rendering`, `verification`,
`notifications`, `audit` are leaf modules that depend only on `kernel`.

#### Communication rules
1. **Synchronous:** a module calls another only through its public `__init__` interface and receives DTOs, never ORM objects.
2. **Asynchronous:** cross-cutting reactions use **domain events** (`RecipientSigned`, `EnvelopeCompleted`, `EnvelopeDeclined`, `VersionApproved`, …). Events are written to the jobs table **in the same transaction** as the state change (outbox pattern) and dispatched by the worker to subscribers (`notifications`, `audit`, `envelopes`). This keeps `envelopes` unaware of email and makes every reaction retryable.
3. **Data ownership:** a module reads and writes only its own tables. Foreign keys across modules are allowed for integrity; queries joining another module's tables are not.
4. **Leaf modules are pure services:** `detection` and `rendering` take inputs and return outputs; they do not read other modules' data. This is what makes them the first candidates for extraction into separate services.

#### Enforcement
- **Python:** `import-linter` contracts in `make check`: (a) modules may import other modules only via their package root (`signora.modules.x`), never internals (`signora.modules.x.repository`); (b) the layered dependency order above; (c) leaf modules import only `kernel`; (d) `domain.py` imports nothing from FastAPI/SQLAlchemy.
- **TypeScript:** `eslint-plugin-boundaries`: `features/x` may import `shared/*` and `packages/contracts`, not other features' internals.
- **Contract SSoT:** the API's OpenAPI schema is exported and the TS types are generated from it (`make contracts`); a check fails if they drift.
- **Tests per module** live inside the module; cross-module flows are covered by integration tests at the entrypoint level.

### Backend process model
One codebase, two processes, one database:

| Process | Purpose | Handles |
|---|---|---|
| **API** (`entrypoints/api.py`) | fast request/response | HTTP, authentication and sessions, access checks, uploads (store blob + enqueue detection), review/approve, envelope creation, signer link/OTP/consent/submit, status and timeline reads |
| **Worker** (`entrypoints/worker.py`) | background jobs | AI + deterministic detection, DOCX→PDF via Gotenberg, OCR (deferred), PDF finalization (stamp, flatten, certificate), email delivery (`email.send` jobs), reminders and expiry, bulk sends, domain-event dispatch |
| **PostgreSQL** (shared) | single source of truth | application data and the persistent job queue (which is the transactional outbox) |

Rules:
- The API never calls slow or unreliable external services (AI provider, SMTP, Gotenberg) inside a request. It commits the state change and enqueues a job in the same transaction, then returns. Target API p95 ≤ 300 ms excluding uploads.
- External calls happen only in the worker, with timeouts, retries with backoff, and dedupe keys (§5.7).
- Both processes are stateless apart from Postgres and the blob store, so either can be restarted at any time without losing work; the worker can be scaled to N replicas because jobs are claimed with `FOR UPDATE SKIP LOCKED`.
- Stripe Identity is the one exception the API touches: creating a verification session is a fast call the signer is waiting on; the result is confirmed by webhook and re-checked in the worker.

### Frontend
Next.js (App Router, TypeScript strict). Console under `/(console)/*`, signer under `/s/*`. `shared/pdf-canvas`
(pdf.js via `react-pdf` + absolutely-positioned field overlay) is the single implementation used by both the
review editor and the signer page; `shared/signature` wraps `signature_pad`. The frontend holds no business
rules beyond UX hints; all validation is re-done server-side.

---

## 5. Business logic

### 5.1 Status model

**Recipient status:** `pending` (waiting for earlier stage) → `sent` → `opened` (OTP passed) → `viewed` (reached end) → `signed` | `declined`.

**Envelope status** (aggregate, only moves forward):
```
draft ─send─► sent ─any recipient opened─► opened ─any viewed─► viewed
  ─all signer recipients signed─► signed ─all countersigners signed (or none)─► completed
any non-terminal ─any decline─► declined │ ─expires_at passed─► expired │ ─user cancel─► cancelled
```
- Terminal: `completed, declined, expired, cancelled`; all links revoked.
- `signed` (waiting on countersigners) does not expire — the firm is the blocker; reminders go to countersigners.
- Events (`otp_sent`, `identity_verified`, `reminder_sent`, `email_failed`, …) go to the timeline without changing status.

### 5.2 Roles and field keys
- A document version defines roles, each `{slug, label, kind: signer|countersigner}`. Slugs are normalized: `client`, or `client_1..client_n` when the document has several parties of the same kind; `guarantor`, `representative`, `firm`, …
- Field keys: `{role}.{attribute}` for people, `agreement.{attribute}` for the deal, `custom.{slug}` for anything else.
- **Strict person attribute vocabulary:** `full_name, first_name, last_name, email, phone, company, title, address_line1, address_line2, city, state, postal_code, country, date_of_birth`, plus `signature, initials, date_signed`.
- **Derivation rule (deterministic):** if a role needs both `full_name` and `first_name`/`last_name`, the form asks for first + last and derives `full_name = first + " " + last`; if it only needs `full_name`, only that is asked.
- Owner: `sender` (filled at send time, read-only to signers), `recipient` (filled by the role's recipient), `auto` (`date_signed`, envelope id).
- `signature`, `initials`, `date_signed` are always owned by their role's recipient.
- Types: `text, email, date, number, currency, percent, checkbox, signature, initials, date_signed`.

### 5.3 Envelope role mapping
At send time each document role is mapped to an envelope recipient. Same slug across documents ⇒ same recipient by default. A recipient may hold several roles (e.g. `client` in TOS and `recipient` in NDA). Extra signers (FR-18) are recipients without a document role and sign the generated addendum.

### 5.4 Settings resolution
Workspace defaults → project settings → per-envelope override at send time (reminder interval, max reminders, expiry). Documents carry no reminder settings because one envelope bundles several documents.

### 5.5 Reminders
`next_reminder_at` per recipient (indexed). Worker every 60 s: due recipients on non-terminal envelopes → enqueue reminder, increment count, compute next. `reminder_urgent` when `expires_at − now ≤ interval`. Stop at `max_reminders`, on terminal states, or once the recipient signed.

### 5.6 Access policy (one function, tested as a matrix)
| Action | Workspace read/write | Project read/write | Project read (default) |
|---|---|---|---|
| List projects, documents, counts | ✓ | ✓ | ✓ |
| See envelopes, recipients, values, downloads | ✓ | ✓ | ✗ |
| Upload / review / approve / send / bulk | ✓ | ✓ | ✗ |
| Countersign | only the designated user for that role |
| Create projects, manage members & grants, project settings | ✓ | ✗ | ✗ |

### 5.7 Idempotency and failure recovery
Two layers, both enforced by the database rather than the UI:

1. **Idempotency keys** on **create** actions the client may retry (send envelope, upload, invite, create project, remind/resend, bulk confirm), per the IETF draft and Stripe: missing key ⇒ 400, reuse with a different request ⇒ 422, duplicate while the first is in flight ⇒ 409 + `Retry-After`. State changes (submit, decline, countersign, approve) do not use keys; they are guarded updates (item 2) that return their original result when repeated. Full contract: backbone LLD topic 3.
2. **Guarded state transitions.** Every transition is a conditional update inside the same transaction as its side-effect rows:
   ```sql
   UPDATE recipients SET status='signed', signed_at=now()
   WHERE id=:id AND status IN ('opened','viewed') RETURNING id;
   ```
   Zero rows ⇒ already done ⇒ return the current state; field values and the audit event are written only when the update returned a row. The same pattern guards `signed → completed`.
3. **Single finalization.** The transaction that makes the envelope eligible for completion enqueues `finalize` with `jobs.dedupe_key = 'finalize:{envelope_id}'` (unique). The finalize job is itself idempotent: it skips documents that already have `final_sha256`, writes blobs content-addressed (re-running produces the same hash and no duplicate), builds the certificate from stored timestamps only, and flips `signed → completed` with a guarded update.
4. **Emails as jobs with a delivery record.** Each email is an `email_messages` row (owned by `notifications`) plus an `email.send` job with a unique dedupe key (e.g. `email:completed:{envelope}:{recipient}`). Business state is committed first; an email failure only affects its delivery record. Retries follow the job backoff (backbone LLD §1.4: 30 s doubling to 1 h, 8 attempts); after the last attempt the record is `failed`, shown as a warning badge on the envelope/recipient with a **Retry** button that re-enqueues it. SMTP cannot be exactly-once (a crash between server acceptance and our commit could resend), so each email carries a deterministic `Message-ID` derived from its record id, letting mail clients collapse duplicates. Exact `email_messages` schema: Phase 7 LLD.
5. **Webhooks** (Stripe) deduplicated by event id.
6. **Jobs** are retried with backoff; a job whose lock is older than its timeout is reclaimed.

### 5.8 Edge cases
- Link opened after expiry/cancel → "no longer available" page, no document shown.
- Recipient email changed → old token revoked, new token issued, audit event.
- Same key with conflicting types across bundled documents → conflict shown; send blocked until resolved by remapping.
- New version uploaded while envelopes are in flight → they keep their pinned version.
- Duplicate email in a bulk batch or within one envelope's roles → flagged in preview (one person holding two roles is allowed only when the user confirms).
- Detector anchor that doesn't resolve → dropped and counted; never invents coordinates.
- Countersigner loses read/write while envelopes await them → blocking warning to reassign.

---

## 6. Data design (Postgres, Alembic migrations)

All tenant tables carry `workspace_id` (FK, indexed) and every repository query filters on it.

| Table | Key columns |
|---|---|
| `workspaces` | id, name, created_by, created_at |
| `users` | id, email (citext unique), password_hash (argon2id), name, saved_signature_blob, saved_initials_blob |
| `memberships` | workspace_id, user_id, access (`read`/`read_write`) — PK (workspace_id, user_id) |
| `invites` | id, workspace_id, email, access, token_hash, expires_at, accepted_at |
| `sessions` | id_hash, user_id, workspace_id, csrf_hash, expires_at, ip, ua |
| `projects` | id, workspace_id, name, description, poc_emails[], reminder_interval_h, max_reminders, expiry_days, access_code_hash, require_id_verification |
| `project_grants` | project_id, user_id, access (`read_write`) |
| `project_countersigners` | project_id, user_id, role_slug_default |
| `documents` | id, workspace_id, project_id, name, description, current_version_id, archived_at |
| `document_versions` | id, document_id, version_no, source_blob_sha, pdf_blob_sha, page_count, page_sizes jsonb, status (`processing/needs_review/needs_ocr/approved/failed`), approved_by, approved_at |
| `detection_results` | id, version_id, detector (`deterministic/ai/merged`), output jsonb (frozen), model, mode, tokens_in, tokens_out, cost_usd, duration_ms, dropped_anchors |
| `roles` | id, version_id, slug, label, kind (`signer/countersigner`), origin_detection_id |
| `fields` | id, version_id, role_id (null = agreement/custom), key, label, type, owner, required, origin_detection_id, origin_item_id |
| `placements` | id, field_id, page, x0, y0, x1, y1 (PDF points, top-left origin), origin_item_id |
| `review_metrics` | version_id, detector, tp, fp, fn, precision, recall, f1, relabeled, retyped, role_changed, mean_iou_tp, placement_tp/fp/fn |
| `envelopes` | id, workspace_id, project_id, status, expires_at, reminder_interval_h, max_reminders, created_by, bulk_batch_id, completed_at |
| `envelope_documents` | envelope_id, version_id, position, final_blob_sha, final_sha256 |
| `recipients` | id, envelope_id, kind (`signer/countersigner`), name, email, user_id (countersigners), stage (1 signers, 2 countersigners), status, token_hash, revoked_at, otp_hash, otp_expires_at, otp_attempts, verified_methods[], identity_session_id, reminders_sent, next_reminder_at, signed_at, ip, ua |
| `recipient_roles` | recipient_id, version_id, role_id — unique (envelope, version, role) |
| `field_values` | envelope_id, field_id, recipient_id, value, blob_sha, filled_at — unique (envelope_id, field_id) |
| `bulk_batches` / `bulk_rows` | batch: id, project_id, blob_sha, status · rows: batch_id, row_no (unique pair), data jsonb, errors jsonb, envelope_id |
| `identity_checks` | id, workspace_id, recipient_id, provider (`stripe`), provider_session_id, status, last_event_id, verified_at (owned by `verification`) |
| `idempotency_keys` | authoritative schema: backbone LLD §3.5 |
| `jobs` | authoritative schema: backbone LLD topic 2 |
| `email_messages` | delivery record per email (recipient refs, template, status, last error, provider message id); schema in the Phase 7 LLD |
| `audit_events` | authoritative schema: backbone LLD §4.6 (keyed by `(chain_id, seq)`, no `prev_hash`) — append-only (triggers) |

Indexes: `envelopes(workspace_id, project_id, status)`, `recipients(token_hash)` unique,
`recipients(next_reminder_at) WHERE status IN ('sent','opened','viewed')`. Indexes for `jobs`, `idempotency_keys` and
`audit_events` are defined in the backbone LLD.

---

## 7. Detection pipeline & algorithms

```
upload ─► normalize ─► classify pages ─► layout ─┬─► deterministic detector ─┐
          (Gotenberg)  (text vs image-only)       │                          ├─► merge ─► needs_review
                                                  └─► AI detector ───────────┘
```

### 7.1 Shared steps
1. **Normalize.** DOCX → PDF via Gotenberg. Store both blobs; SHA-256.
2. **Classify pages.** < 20 extractable characters and an image covering > 50 % ⇒ image-only. All image-only ⇒ `needs_ocr` (§15).
3. **Layout.** `page.get_text("words")` and `get_text("dict")` → words, lines (stable ids `p{page}-l{n}`), font size/bold for headings, drawn lines/rects (`page.get_drawings()`) for signature rules and table cells. `pymupdf4llm` Markdown view for the AI.

### 7.2 Deterministic detector (no AI, separately scored)
- AcroForm widgets (`page.widgets()`): exact bbox, type, name.
- Underscore / dotted-leader runs, and **drawn horizontal lines** (vector graphics) with a label left or below.
- Placeholders: `[...]`, `{{...}}`, `<<...>>`, `«...»`.
- Label lexicon → attribute mapping (`Name`→full_name, `Email`, `Date`, `Address`, `Phone`, `Title`, `Company`, `Signature`/`Sign here`/`By:`→signature, `Initials`, checkbox glyphs).
- **Role inference by rules:** signature blocks grouped by proximity; block headers (`CLIENT:`, `LANDLORD`, `TENANT 1`, `COMPANY`) → role slug; party definitions in the preamble (`("Client")`) map labels to roles.
- Empty table cells adjacent to a label cell.
Output uses the same `DetectionResult` schema as the AI detector, with a confidence per item.

### 7.3 AI detector
- **Whole mode** when the line-tagged document is ≤ `AI_WHOLE_DOC_MAX_TOKENS` (default **40k**, ≈ 60 pages): one call with the tagged text, the deterministic candidates as hints, and the uploader's description.
- **Chunked mode** otherwise: (a) a brief call on the first ~6 pages + heading outline → parties, roles, defined terms; (b) candidate batches of ≤ 40, each with its **child** window (±3 lines) and **parent** section heading + the brief; (c) a recall sweep over 6-page windows with 1-page overlap for variable spans without blanks (pre-filled sample values). Concurrency 4.
- Cost note: even 120k input tokens is ≈ $0.012 on `gpt-6-luna`; the 40k threshold is chosen for latency and attention quality (long single prompts miss fields deep in the document), not cost.
- Structured output per field: `{role, attribute|custom_key, label, type, owner, required, anchors:[{line_id, text, position: replace|after|below}], confidence}` and a `roles` list.
- **Resolution** is deterministic: line id → hash map → words → bbox. Unresolvable anchors are dropped and counted.

### 7.4 Merge
Union of both detectors; placements overlapping with IoU > 0.5 are one item. Precedence: AcroForm > AI (semantic label/role) > rules (geometry). Low-confidence items unclaimed by the other detector are shown dashed. The merge policy is tuned using the eval harness; each detector's standalone score is kept so we can decide whether to rely more on the deterministic path.

### 7.5 Complexity
W = words, L = lines, C = candidates, P = pages.
Layout O(W). Rules: one regex pass per line O(W); drawn-line matching per page via sort on y then sweep, O(D log D) for D drawings. Line lookup O(1) (hash map) ⇒ resolution O(C). Merge/dedupe: per-page sort + sweep on x0, O(C log C).
AI calls: whole mode 1; chunked ⌈C/40⌉ + ⌈P/5⌉ + 1 = O(C + P), 4-way parallel.
Total CPU O(W + C log C + D log D). *Rejected:* pairwise IoU O(C²); LLM-produced coordinates (unreliable); NER pre-pass (skipped by decision).

### 7.6 Accuracy metrics (corrected)
v1 used `precision = kept / ai_count`, `recall = kept / final_count`, where "kept" = AI field not deleted. That over-counts: a field that was kept but moved to another place, given another type, or assigned to the wrong party was counted as correct, and fields with many placements (initials on 30 pages) were counted once.
v2 definition, computed per detector (`deterministic`, `ai`, `merged`):
- **Match:** a detected item and an approved item match when their placements overlap with IoU ≥ 0.5 **and** their type family agrees (signature/initials/date_signed vs data vs checkbox). Matching is one-to-one, greedy by descending IoU per page (O(n log n)).
- **TP** = matched pairs; **FP** = detected, unmatched (deleted or moved away); **FN** = approved, unmatched (added by the human).
- precision = TP / (TP + FP); recall = TP / (TP + FN); F1.
- Reported separately: among TPs, % relabeled, % retyped, % with wrong role; mean IoU of TPs.
- Computed at **placement level** and at **field level** (a field is TP if ≥ 1 placement matched and its key matches after role normalization).
The same function is used in-product (detector vs human-approved) and in the private eval harness (detector vs ground truth).

---

## 8. Interface contracts (REST, JSON; `/api/v1`)

Create endpoints require `Idempotency-Key` (backbone LLD §3.2); state-change endpoints are guarded and return their original result when repeated. Errors: RFC 9457 problem+json (backbone LLD §7.1).

Auth & tenancy: `POST /auth/signup`, `POST /auth/login`, `POST /auth/logout`, `GET /me`, `POST /invites`, `POST /invites/{token}/accept`, `GET/PATCH /members`.
Projects: `GET/POST /projects`, `GET/PATCH /projects/{id}`, `PUT /projects/{id}/grants`, `PUT /projects/{id}/countersigners`.
Documents: `POST /projects/{id}/documents` (multipart), `POST /documents/{id}/versions`, `GET /documents/{id}`, `GET /versions/{id}` (status, roles, fields, metrics), `GET /versions/{id}/pdf`, `PUT /versions/{id}/fields`, `POST /versions/{id}/approve`.
Envelopes: `POST /projects/{id}/send-form?versions=…` (generated form schema), `POST /projects/{id}/envelopes`, `GET /projects/{id}/envelopes?status=`, `GET /envelopes/{id}` (recipients, timeline, email delivery state), `POST /envelopes/{id}/cancel`, `POST /recipients/{id}/resend|remind`, `PATCH /recipients/{id}`, `GET /recipients/{id}/link`, `GET /envelopes/{id}/download`, `POST /emails/{id}/retry`.
Bulk: `GET /projects/{id}/bulk-template?versions=…&format=csv|xlsx`, `POST /projects/{id}/bulk` (preview), `POST /bulk/{id}/confirm`.
Signer (`/api/v1/sign`): `POST /open`, `POST /otp`, `POST /access-code`, `POST /identity/start`, `GET /identity/return`, `GET /session`, `GET /documents/{n}/pdf`, `POST /consent`, `POST /events` (viewed-to-end), `POST /submit`, `POST /decline`, `GET /receipt`.
Countersign: `POST /envelopes/{id}/countersign` (console) and the signer routes for countersigner recipients.
Webhooks: `POST /webhooks/stripe` (signature-verified, event-id deduped).

---

## 9. Security & legal design

- **Signing links:** 256-bit random token; only `sha256(token)` stored; scoped to one recipient; revoked on terminal state or email change. First hit exchanges it for an httpOnly, Secure, SameSite=Strict pre-auth cookie and redirects to a token-free URL.
- **OTP:** 6 digits (`secrets`), hashed, 10-minute TTL, 5 attempts then a new code is required; resend cooldown 60 s; success ⇒ 30-minute sliding signer session.
- **Firm access code (optional):** per project, Argon2id, shared out-of-band; same attempt limits.
- **ID verification (optional):** Stripe Identity VerificationSession (`type=document`), test mode; hosted redirect with `return_url`; confirmed server-side by retrieving the session and via verified webhook. The one-time Stripe URL is never emailed or logged.
- **Rate limits:** per IP and per recipient on `/sign/*`, login, signup (token bucket; in-memory is acceptable for this single-instance deployment and documented).
- **Headers:** HSTS, strict CSP with nonces, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex, nofollow` on `/s/*`, minimal `Permissions-Policy`.
- **Console auth:** Argon2id, server-side sessions, CSRF double-submit token, login throttling.
- **Documents** served only via authorized endpoints; blobs never publicly addressable.
- **Integrity:** SHA-256 of source and final PDFs on the certificate; audit hash chains per envelope and per workspace, `hash = sha256(previous entry's hash ‖ canonical_json(entry))` (fields and canonical form: backbone LLD §4.3); triggers block UPDATE/DELETE/TRUNCATE on `audit_events` and UPDATE/DELETE on approved versions/fields.
- **ESIGN/UETA:** consent with disclosure before viewing, intent statement at the final action, attribution (email OTP + optional access code / ID), retention (final PDF + certificate), copy delivered to every signer, signing time and verification method shown to the signer and on the certificate (FR-24).
- **Secrets** only in `.env` (git-ignored); `.env.example` committed. **Test data only.**

---

## 10. Notifications (templates)

| Template | To | Trigger |
|---|---|---|
| `team_invite` | invitee | invite created |
| `sign_request` | each signer recipient | envelope sent / resent |
| `otp_code` | recipient | link opened |
| `reminder` / `reminder_urgent` | recipients who still have to act | scheduler |
| `signed_receipt` | the signer who submitted | own submit (envelope not yet complete) |
| `countersign_request` | countersigners | all signers signed |
| `completed_copy` | all recipients + POC (PDF attached) | completion |
| `poc_all_signed` / `poc_declined` / `poc_expired` | POC + countersigners | events |

Every email is an `email_messages` delivery record sent by an `email.send` job (§5.7). Dev uses Mailpit; real sends use Gmail SMTP (587/STARTTLS, app password).

---

## 11. Test strategy

- **Unit:** rules, role inference, anchor resolution, IoU/matching, state machine, access matrix, token/OTP lifecycle, CSV/XLSX parsing + template generation, field derivation, reminder math, audit hash chain, idempotency (repeat submit/send/finalize).
- **Integration (pytest + Postgres in Docker):** tenant isolation (A cannot read B by id), read-only users see counts only, full multi-signer envelope lifecycle with Mailpit capture, concurrent double-submit (two parallel requests ⇒ one signature, one final PDF, one completion email), SMTP failure then retry.
- **E2E (Playwright):** grader path — sign up → project → upload unseen doc → review → approve → send to 2 signers + countersigner → OTP → sign → countersign → completed download.
- **Security checks:** header assertions, token reuse after revoke, OTP brute-force lockout.

### Private detection eval (not committed)
The corpus, ground truth, and eval runner live in `eval/` which is **git-ignored** (internal R&D, not part of the product). The product only ships the metric function (§7.6) and in-product review metrics. Summary numbers may be quoted in the submission description.

| # | Document | Edge cases |
|---|---|---|
| 1 | Mutual NDA (PDF) | two-party blocks, underscores, `By:/Name:/Title:/Date:` |
| 2 | SaaS Terms of Service | acceptance block, initials on every page |
| 3 | Residential lease | **two tenants + landlord + guarantor**, currency, dates, checkboxes |
| 4 | USCIS Form I-983 (official public form) | native AcroForm widgets, dense layout |
| 5 | Job offer letter (**DOCX**) | `[Candidate Name]` placeholders, Gotenberg conversion |
| 6 | Employment contract (~30 pages) | repeated name, signature only at end |
| 7 | B2B Master Services Agreement (~120 pages) | chunked mode, signature blocks inside an exhibit |
| 8 | Law-firm engagement letter | **pre-filled sample values** (no blanks), contingency %, firm countersign |
| 9 | Consent & release form | two-column layout, checkbox groups, table-based signature block |
| 10 | Vendor onboarding form (fillable PDF) | AcroForm text/checkbox/signature widgets, landscape page |
| 11 | Scanned agreement (image-only) | **deferred:** OCR / multimodal path — reminder for the end |

---

## 12. Deployment

`docker compose up -d` → postgres, gotenberg (+ gotenberg-gateway), api, worker, web, caddy (+ mailpit in the `dev` profile).
Caddy listens on `127.0.0.1:3100`, which the existing Funnel config proxies: `https://hemanth.tail50655e.ts.net` → `127.0.0.1:3100` (verified 2026-11-06; Funnel ports 443/8443/10000 allowed).

---

## 13. Included features (summary for the submission)
Multi-tenant workspaces · department projects · read / read-write access · versioned immutable documents ·
deterministic + AI field detection with human review · multi-signer + multi-countersigner envelopes · dynamic send
form · bulk CSV/XLSX send · secure links (hashed tokens, email OTP, optional access code, optional Stripe Identity) ·
minimal signer page with explicit consent and confirmation · reminders with urgency · POC notifications ·
flattened final PDF with certificate · hash-chained audit log · idempotent operations and retryable email.

## 14. Deliberately left out
OAuth/SSO, payments/retainers, CRM/practice-management integrations and public API, SMS, notarization,
redlining/negotiation, custom routing order (beyond signers → countersigners), in-person signing, AI "looks fake"
checks, NER pre-pass, PAdES cryptographic PDF signatures (stretch), mobile apps, EU qualified signatures, multi-region HA.

## 15. Deferred (do last)
- **OCR / image-only PDFs:** detected now (FR-13); later add an OCR path (`ocrmypdf`, a `gpt-6-luna` image-input pass, or `pdf-inspector` classification) and test with corpus #11.

---

## Delivery plan (v4: vertical feature slices, core first)

**How we build.** One feature at a time, end to end: its own LLD (`docs/design/features/NN-<slug>.md`, brainstormed and agreed before code) → backend module → frontend screens from the design system → tests → one branch and one PR. Each commit is one task inside the feature. Before a PR is merged: `make check` passes locally (lint, types, import boundaries, tests, web build) and the feature is tested manually; there is no hosted CI.

**Order.** The core signing path and its business rules and security come first, then hardening. Nicer features (bulk send, ID verification, OCR, extra-signer addendum, phone-specific signer, landing page) come only after the core is hardened. The modular structure (ADR-008) applies from the first line.

| Phase | Branch | Feature | Backend | Frontend (prototype screens) | Tier |
|---|---|---|---|---|---|
| 0 | `phase-0/foundation` | Foundation | design, infra, installer | design system reference | done |
| 1 | `phase-1/backbone` | Backbone | `kernel` (config, db + Alembic, logging, errors, idempotency, jobs, events, blob store, clock), `audit` module, API + worker entrypoints, import-linter, `make check` (local quality gate) | Next.js scaffold, tokens + base components, app shell | core |
| 2 | `phase-2/accounts` | Accounts & workspaces | `identity_access`: signup, login, sessions, CSRF, workspaces, members, invites, access policy | 02 sign up, 03 log in, 04 invite, 19 members | core |
| 3 | `phase-3/projects` | Projects | `projects`: CRUD, settings, grants, countersigners | 05 home, 06 new project, 08 read-only, 09 settings | core |
| 4 | `phase-4/documents` | Documents & versions | `documents`: upload, Gotenberg conversion, immutable versions, hashes | 10 documents, 11 upload | core |
| 5 | `phase-5/detection` | Field detection | `detection`: layout, deterministic detector, AI detector, merge, metric; private eval | 12 detecting | core |
| 6 | `phase-6/review` | Field review & approval | roles/fields/placements, approve, review metrics | 13 review canvas | core |
| 7 | `phase-7/envelopes` | Envelopes & sending | `envelopes`: send form generation, recipients, role mapping, state machine; `notifications`: outbox + Gmail SMTP | 14 new envelope, 07 envelopes list, 16 envelope detail | core |
| 8 | `phase-8/signing` | Signing | `signing`: link exchange, OTP, consent, submit validation, decline | 21–27 signer flow | core |
| 9 | `phase-9/completion` | Countersign & completion | `rendering`: stamp, flatten, certificate; countersign flow; completed copies | 17 countersign, 18 completed | core |
| 10 | `phase-10/lifecycle` | Reminders, expiry, notifications | scheduler: reminders (+ urgent), expiry, POC notices, email retry | badges, retry notice, 20 audit log | core |
| 11 | `phase-11/hardening` | Hardening | security review, rate limits, headers, tenant-isolation and concurrency tests, E2E grader path on the Funnel URL | polish, accessibility, empty/error states | hardening |
| 12+ | `phase-12/…` | Later features | bulk CSV/XLSX; Stripe Identity; extra-signer addendum; OCR / image-only PDFs; phone signer (28); landing page (01) | — | later |

## Task Tracker

Each feature's detailed task list lives in its LLD file and is copied here as it starts.

| # | Task | Status | Evidence of completion |
|---|------|--------|------------------------|
| P0.1 | Research + design doc | done | this file (v1–v4) |
| P0.2 | Infra: Postgres 18.4 + Gotenberg 8.40.0 in `infra/compose.yaml`, `make up` | done | 2026-11-06: both healthy; `select version()` → 18.4, checksums on, scram-sha-256; Gotenberg `/health` up, `/version` 8.40.0, DOCX → 1-page PDF via `POST /forms/libreoffice/convert` (field `files`), text verified with pdftotext |
| P0.3 | Backend Python project + `./install.sh` | done | commit 78102ec; clean-copy install and pip requirements install verified 2026-11-06 |
| P0.4 | Design system reference | done | `docs/design-system/` |
| P0.5 | Branch / commit / PR workflow | done | PR template (`.github/pull_request_template.md`) |
| P0.6 | PR #1 review fixes: host-first env defaults, Gotenberg network isolation + gateway, installer hardening, single port variables, pinned/verified uv, Gotenberg log flag | done | commits e0e18d6, 85aaaea, 6f9b4e5 and follow-ups on `phase-0/foundation`; tests in commit messages |
| P1 | Backbone | done — LLD and tasks 1.1–1.13 in `docs/design/features/01-backbone.md` (carried requirements met: repo-root path resolution with a cross-directory test; `make check`) | branch `phase-1/backbone`; `make check` passes; stack live on the Funnel URL |
| P2–P10 | Core features | todo. Carried into Phase 2: sign-up must not reveal whether an email is already registered (account enumeration), including on retries | — |
| P11 | Hardening | todo. Carried items: Postgres row-level security; restricted DB role for `audit_events` (INSERT/SELECT only); orphaned-blob cleanup that cannot race a concurrent upload deduplicating against the same object (e.g. re-check references and object age inside one locked pass); Playwright E2E | — |
| P12+ | Later: bulk send, Stripe Identity, extra-signer addendum, **OCR / image-only PDFs (reminder)**, phone signer, landing | todo | — |
