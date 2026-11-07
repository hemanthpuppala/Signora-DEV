# Phase 1 — Backbone (LLD)

Parent design: [`../signora-platform.md`](../signora-platform.md) · Branch: `phase-1/backbone`

The backbone is the shared plumbing every later feature uses. It contains no business features (no accounts,
documents or signing). This document is written topic by topic; a topic is recorded here only once it has been
agreed.

## Topic status

| # | Topic | Status |
|---|---|---|
| 1 | Background jobs and events | **agreed** (2026-11-07) |
| 2 | Jobs table schema | **agreed** (2026-11-07) |
| 3 | Idempotency: server contract, schema, client reconnect behaviour | **agreed** (2026-11-07) |
| 4 | Audit log: chain scope, system events, schema | **agreed** (2026-11-07) |
| 5 | File storage | **agreed** (2026-11-07) |
| 6 | Configuration and path resolution | **agreed** (2026-11-07) |
| 7 | Errors, logging, health APIs | **agreed** (2026-11-07) |
| 8 | Frontend shell | **agreed** (2026-11-07) |
| 9 | Quality gate (`make check`) and runtime (compose, Caddy) | **agreed** (2026-11-07, written on owner's instruction from the earlier proposals) |
| 10 | Phase 1 FRs, NFRs, ADRs, tasks | **agreed** (2026-11-07, written on owner's instruction) |

---

## Topic 1 — Background jobs and events

### 1.1 What a background job is

Work the application does **after** answering the user, in the separate worker process. A job is used when the
work is:

- **slow** — the user should not wait on it (AI detection takes 10 s to minutes);
- **unreliable** — it depends on an outside service that can fail and must be retried (OpenAI, Gmail);
- **scheduled** — it must happen later or on a timer (reminders, expiry);
- **exactly-once** — it must not run twice even under concurrency (final PDF).

The API commits the user's action and enqueues the job **in the same database transaction**, then responds.
If the transaction rolls back, the job never existed; if it commits, the job is guaranteed to exist
(transactional outbox).

### 1.2 Job catalogue

| Job kind | Enqueued by | What the worker does | Why it is a job | Phase |
|---|---|---|---|---|
| `detection.run` | Document upload | Convert DOCX via Gotenberg, extract layout, run rule and AI detectors, merge, store fields | Slow; AI call can time out and must retry | 4–5 |
| `email.send` | Any feature that emails (invite, sign request, OTP code, receipt, countersign request, completed copy, POC notices) | Deliver one email via the configured provider | SMTP is slow/unreliable; email failure must never block or roll back business state | 7 |
| `envelope.finalize` | Last required recipient signs | Stamp signatures, flatten, append certificate, hash, then enqueue completed-copy emails | Seconds of CPU; must run exactly once | 9 |
| `sweep.reminders` | Scheduler, every minute | Find recipients whose next reminder is due; enqueue one `email.send` each | Time-based | 10 |
| `sweep.expiry` | Scheduler, every minute | Mark overdue envelopes expired; publish `EnvelopeExpired` | Time-based | 10 |
| `sweep.housekeeping` | Scheduler, hourly | Delete succeeded jobs older than 7 days and expired idempotency records | Time-based | 1 |
| `event:<Event>:<subscriber>` | `publish()` (see 1.5) | Run one subscriber's reaction to one event | Each reaction retries independently | 1+ |
| *later* `bulk.send_row` | Bulk upload confirmed | Create and send one envelope per spreadsheet row, throttled | Volume; provider daily cap | 12+ |
| *later* `stripe.webhook` | Stripe webhook received | Record an ID-verification result | Safe retry | 12+ |

### 1.3 Concurrency model

- **API (request path):** every request is its own transaction and locks only the rows it touches, so different
  users (and different envelopes) proceed in parallel. Each signer gets their confirmation independently of others.
- **Worker:** runs up to `WORKER_CONCURRENCY` jobs at once (default **8**, thread pool). Jobs are independent; one
  signer's receipt does not wait for another signer's finalize.
- **Scaling:** more worker processes can be started at any time. Claiming uses `FOR UPDATE SKIP LOCKED`, so two
  workers never take the same job.
- **Ordering:** due jobs are claimed in `run_at` order (FIFO among ready jobs). There is no ordering guarantee
  between unrelated jobs, and none is needed.
- **Throughput ceilings (not code):** the email provider (Gmail ≈ 500 recipients/day) and CPU for PDF
  finalization; both scale by swapping the provider or adding worker processes.

### 1.4 Retries, leases and failure

- Each job kind is declared once in code with its handler and policy — the **single source** for retry limits:

  | Kind | Max attempts | Lease (time limit) |
  |---|---|---|
  | `email.send` | 8 | 60 s |
  | `envelope.finalize` | 5 | 5 min |
  | `detection.run` | 3 (AI cost) | 10 min |
  | `sweep.*` | 3 | 2 min |
  | `event:*` | 8 | 2 min |

- **Backoff:** after a failure the job is re-queued at `now + min(30 s × 2^(attempts−1), 1 h)` with ±20 % random
  jitter (e.g. email: 30 s, 1 m, 2 m, 4 m, 8 m, 16 m, 32 m, 1 h ≈ 2 h total).
- **Dead jobs:** after the last attempt the job becomes `dead`, keeps its `last_error`, and is not deleted
  automatically, so failures can be diagnosed and retried by hand.
- **Leases:** a claimed job gets `lease_expires_at = now + lease`. If the worker crashes, the job is reclaimed after
  the lease ends and counts as an attempt.
- **Success is atomic with the work:** the handler's database writes and marking the job `succeeded` happen in one
  transaction. On error that transaction rolls back and a separate transaction records the attempt, the error and
  the next `run_at`.
- **Side effects outside the database are at-least-once.** An email can be sent and the worker can crash before
  committing; the retry then sends again. Handlers therefore must be idempotent or tolerate a duplicate (emails
  carry a deterministic `Message-ID` so clients collapse duplicates — Phase 7).

### 1.5 Events (a thin layer over jobs)

Modules stay independent: the module where something happens announces it; modules that care react. Envelopes,
for example, never call the notifications module.

- `publish(event)` is called inside the business transaction. For each subscriber registered for that event type
  it enqueues one job `event:<EventName>:<subscriber>` with `dedupe_key = "event:<event_id>:<subscriber>"`.
- One subscriber failing does not affect the others; each retries on its own.
- There is **no separate events table**; an event is the payload of its jobs.
- Subscribers are registered in each module's `handlers.py` at startup.

Example — a signer submits:
```
API transaction:  recipient → signed · audit entry · publish(RecipientSigned)
                  → job event:RecipientSigned:notifications   (send receipt, notify POC if all signed)
                  → job event:RecipientSigned:envelopes       (if all signers done → enqueue envelope.finalize)
```

### 1.6 Exactly-once work

Two independent guards:
1. **Dedupe key** — `INSERT … ON CONFLICT (dedupe_key) DO NOTHING`; e.g. `finalize:<envelope_id>` cannot be queued twice
   while its row exists.
2. **State check in the handler** — finalize first does a guarded update
   (`… WHERE id = :id AND status = 'signed'`); if the envelope is already completed it exits without doing anything.

Dedupe keys are released when housekeeping deletes old succeeded rows; guard 2 keeps the work exactly-once after that.
Recurring work puts its time slot in the key (`sweep:reminders:2026-11-07T10:14`), so several workers or schedulers
can never run the same sweep twice.

### 1.7 Waking the worker

`enqueue` issues `pg_notify('jobs', kind)` in the same transaction; Postgres delivers the notification only on commit.
The worker `LISTEN`s and claims immediately, with a 5-second poll as a fallback (missed notification, scheduled
`run_at`, reclaimed lease).

### 1.8 Interfaces (sketch)

```python
# kernel/jobs
@dataclass(frozen=True)
class JobKind:
    name: str
    handler: Callable[[UnitOfWork, dict], None]
    max_attempts: int
    lease: timedelta

def register(kind: JobKind) -> None: ...
def enqueue(uow, kind: str, payload: dict, *, run_at: datetime | None = None,
            dedupe_key: str | None = None) -> bool: ...          # False if deduplicated

# kernel/events
class DomainEvent(BaseModel):                                     # immutable, JSON-serialisable
    event_id: UUID; occurred_at: datetime; workspace_id: UUID | None
def subscribe(event_type: type[DomainEvent], subscriber: str) -> Callable: ...
def publish(uow, event: DomainEvent) -> None: ...
```

### 1.9 Tests that prove it

- Enqueue rolled back with its transaction → job does not exist.
- Two workers, 200 jobs → every job runs exactly once.
- Failing handler → attempts and backoff increase; after the last attempt the job is `dead` with `last_error`.
- Worker killed mid-job → job reclaimed after the lease and completed.
- Same `dedupe_key` enqueued twice (also concurrently) → one row.
- One event, two subscribers, one failing → the other still succeeds; the failing one retries alone.
- Housekeeping deletes only `succeeded` rows older than 7 days.

### 1.10 Complexity

Claim: partial index on `run_at` for queued jobs ⇒ O(log n + k) for n queued jobs and batch size k.
Enqueue with dedupe: one unique-index insert, O(log n). Reclaim: partial index on `lease_expires_at` ⇒ O(log n + r).
Housekeeping delete: index range on `finished_at` ⇒ O(log n + d).

---

## Topic 2 — Jobs table schema

```sql
CREATE TABLE jobs (
  id               uuid        PRIMARY KEY DEFAULT uuidv7(),
  kind             text        NOT NULL,
  payload          jsonb       NOT NULL DEFAULT '{}',
  status           text        NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued', 'running', 'succeeded', 'dead')),
  dedupe_key       text        UNIQUE,
  run_at           timestamptz NOT NULL DEFAULT now(),
  attempts         integer     NOT NULL DEFAULT 0,
  lease_expires_at timestamptz,
  last_error       text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz
);
CREATE INDEX jobs_due      ON jobs (run_at)           WHERE status = 'queued';
CREATE INDEX jobs_lease    ON jobs (lease_expires_at) WHERE status = 'running';
CREATE INDEX jobs_finished ON jobs (finished_at)      WHERE status = 'succeeded';
```

| Column | Purpose |
|---|---|
| `id` | Identity of the job (UUIDv7: time-ordered, good index locality) |
| `kind` | Selects the registered handler and its policy |
| `payload` | Handler input, e.g. `{"envelope_id": "…"}`; never secrets |
| `status` | Lifecycle; drives the partial indexes and the dead-job view |
| `dedupe_key` | Prevents queuing the same work twice (§1.6) |
| `run_at` | Earliest start: scheduling and retry backoff |
| `attempts` | Drives backoff and the dead cutoff (limit comes from the job kind in code) |
| `lease_expires_at` | Reclaims jobs from crashed workers |
| `last_error` | Diagnosis of failures |
| `created_at` | Queue latency metrics |
| `finished_at` | Retention: succeeded rows deleted after 7 days |

**Removed after review:** `max_attempts` (duplicated the per-kind limit defined in code) and `locked_by` (only
useful for debugging multiple workers; worker identity is in the logs).

**Retention:** `succeeded` rows are deleted after 7 days by `sweep.housekeeping`; `dead` rows are kept.

---

## Topic 3 — Idempotency (safe retries)

Reference: IETF HTTPAPI draft *The Idempotency-Key HTTP Header Field* (draft-ietf-httpapi-idempotency-key-header-07,
Oct 2025; work in progress) and Stripe's API, which follows the same model. Our status codes follow -07.

### 3.1 Problem

A request that creates something can succeed on the server while its response is lost (network blip). The client
retries and, without protection, the action happens twice — e.g. two envelopes and two emails to the client.

### 3.2 Where it applies

Endpoints that **create a record or trigger a side effect that must not repeat** require an `Idempotency-Key`:

| Requires a key | Does not (and why) |
|---|---|
| Create project | Submit signature — guarded state change (`WHERE status IN ('opened','viewed')`) |
| Upload document / new version | Countersign — guarded state change |
| Send envelope(s) | Approve version — guarded state change (`WHERE status = 'needs_review'`) |
| Invite member | Sign-up — unique email rejects a duplicate |
| Remind now, resend (each sends an email) | Settings updates — naturally idempotent (same result when repeated) |
| *later:* confirm bulk send | |

**Guarded actions answer with their result when repeated.** If a guarded action is already in its target state, the
server returns the same success response as the first time (e.g. the signer's confirmation with the original signing
time) instead of an error.

### 3.3 Server contract

| Situation | Response |
|---|---|
| Key missing on an endpoint that requires it | `400` problem+json linking to the API docs |
| First request with a key | Runs normally; the response is stored with the key |
| Repeat after the first completed | The stored status and body are returned; nothing runs again |
| Repeat while the first is still running | `409 Conflict`, `Retry-After: 1` ("a request is outstanding for this key") |
| Same key, different request body | `422` problem+json |
| First request failed (rolled back) | Nothing is stored; a retry runs normally (errors are never replayed) |

- **Key format:** a string of 1–255 printable characters (our frontend sends a UUIDv4).
- **Scope:** `<user_id>:<METHOD> <route template>`, so different users and endpoints never collide.
- **Retention:** 24 hours from creation (configuration), then deleted by `sweep.housekeeping`.

### 3.4 Mechanism

The key row is written **inside the action's own transaction**, before the work:

1. `SET LOCAL lock_timeout = '2s'`, then `INSERT (scope, key, request_hash)`.
2. Conflict with a **committed** row → compare `request_hash`; same → return the stored response; different → `422`.
3. Conflict with an **in-flight** row → Postgres waits on the other transaction; if it has not finished within 2 s
   the lock timeout fires → `409` with `Retry-After: 1`.
4. No conflict → do the work, then `UPDATE` the row with the response, and commit. A rollback removes the key row too.

There is no `in_progress` state column: in-flight rows are invisible to other transactions until they commit,
and the database serializes duplicates.

### 3.5 Schema

```sql
CREATE TABLE idempotency_keys (
  scope           text        NOT NULL,                       -- '<user_id>:POST /api/v1/projects/{id}/envelopes'
  key             text        NOT NULL CHECK (char_length(key) BETWEEN 1 AND 255),
  request_hash    bytea       NOT NULL,                       -- sha256 of the canonical request body
  response_status smallint,                                   -- set before commit; non-null in every committed row
  response_body   jsonb,                                      -- replayed to retries
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope, key)
);
CREATE INDEX idempotency_keys_created ON idempotency_keys (created_at);
```

| Column | Purpose |
|---|---|
| `scope`, `key` | Identify one user action on one endpoint |
| `request_hash` | Detect key reuse with a different request (`422`) |
| `response_status`, `response_body` | The stored answer replayed to retries |
| `created_at` | 24-hour retention |

**Removed after review:** `state` (the transaction itself serializes duplicates) and `expires_at` (always
`created_at` + 24 h; the duration lives in configuration).

**Complexity:** one primary-key insert or lookup per protected request, O(log n), plus one SHA-256 of the body.

### 3.6 Client behaviour after a network blip

1. One key per **user action**, kept (also in `sessionStorage`) until a definite response arrives; every retry
   reuses it.
2. While pending, the button shows "Sending…" and is disabled; on a network error it shows
   "Connection lost — retrying…", never "Failed".
3. Automatic retry with the same key on the browser `online` event and on backoff (1 s, 2 s, 4 s … max 30 s);
   `409` is retried after `Retry-After`.
4. Pressing the button again while an action is pending resends the same key, so it cannot create a duplicate.
5. Server data refetches on reconnect and on window focus, so changes made while offline appear without a reload.

### 3.7 Tests that prove it

- Same key twice (sequential) → one record; second call returns the stored response.
- Same key twice (concurrent) → one record; the other gets the stored response or `409`.
- Same key, different body → `422`. Missing key on a protected endpoint → `400`.
- Failed first request → retry with the same key runs and succeeds.
- Guarded action repeated (e.g. submit after signed) → same success response, no second effect.
- Housekeeping removes keys older than 24 h.

---

## Topic 4 — Audit log

### 4.1 Purpose

A permanent, tamper-evident record of who did what, when, from where. It is used for:

- the **certificate of completion** (who signed, when, IP, user agent, how they were verified);
- the console's **audit log** screen;
- **evidence** if a signature or an admin action is disputed.

Each entry carries a SHA-256 fingerprint that covers its own content **and the previous entry's fingerprint**, so
changing or deleting any earlier entry breaks every fingerprint after it.

### 4.2 Chains

| Chain | Holds | Who can wait on whom |
|---|---|---|
| **Envelope chain** (one per envelope) | Everything about one envelope: sent, link opened, code verified, consent, viewed to end, signed, declined, reminder sent, countersigned, completed | Only people acting on the *same* envelope |
| **Workspace chain** (one per workspace) | Admin and account actions: member invited/joined, access changed, project created/updated, document uploaded, version approved, settings changed, login succeeded/failed | Admin actions within one workspace |
| **System chain** (one, fixed system workspace) | Actions with no workspace yet: sign-up, failed login for an unknown email | — |

Why per envelope: hundreds of signers in one company can submit at the same moment without queuing behind one
workspace-wide lock, and a certificate covers exactly one envelope chain. The audit screen still shows a whole
workspace by filtering on `workspace_id`.

The **system workspace** is a fixed, reserved workspace row (created by the Phase 2 migration), so every entry
has a workspace and the schema has no special NULL case.

### 4.3 Writing an entry

`audit.record(...)` runs **inside the action's own transaction**: if the action commits, so does its entry; if it
rolls back, neither exists. Request context (request id, IP, user agent) is attached automatically.

1. `pg_advisory_xact_lock(<chain_id>)` — serializes appends to this chain only; released at commit.
2. Read the last entry's `seq` and `hash` for the chain (primary-key index, O(log n)); for a new chain use
   `seq = 0` and 32 zero bytes.
3. `hash = sha256(previous_hash ‖ canonical_json(entry))`, insert with `seq + 1`.

**Canonical JSON** (stable bytes for hashing): keys sorted, UTF-8, no insignificant whitespace, timestamps as UTC
ISO-8601 with microseconds, in the spirit of RFC 8785. Audit `data` holds only strings, integers, booleans, lists
and objects — no floating-point numbers — so a database round trip cannot change the bytes.

### 4.4 Verifying a chain

Walk the chain in `seq` order and recompute every hash from the previous one. The chain is intact when `seq` runs
1, 2, 3 … with no gaps and every recomputed hash equals the stored one. A changed entry fails at that entry; a
deleted entry shows as a gap. Cost O(n) for an n-entry chain. Available as `signora audit verify` (CLI) now and as
a console action later.

### 4.5 Protection and its limits

- Database triggers reject `UPDATE`, `DELETE` and `TRUNCATE` on `audit_events`.
- **Limit:** someone with full database control can drop the triggers and rewrite a whole chain consistently; the
  hash chain detects partial edits, not a complete rewrite. Mitigations:
  - **Anchoring (Phase 9):** each completion certificate prints its envelope chain's final hash. Signers keep copies,
    so a later rewrite no longer matches what they hold.
  - **Hardening phase:** the app connects as a database role with only `INSERT`/`SELECT` on `audit_events`;
    migrations run as the owner.

### 4.6 Schema

```sql
CREATE TABLE audit_events (
  chain_kind   text        NOT NULL CHECK (chain_kind IN ('system', 'workspace', 'envelope')),
  chain_id     uuid        NOT NULL,                 -- envelope id, or workspace id for workspace/system chains
  seq          bigint      NOT NULL CHECK (seq >= 1),
  workspace_id uuid        NOT NULL,                 -- FK to workspaces added in Phase 2
  occurred_at  timestamptz NOT NULL,
  actor_type   text        NOT NULL CHECK (actor_type IN ('user', 'recipient', 'system')),
  actor_id     uuid,                                 -- NULL for system
  actor_label  text,                                 -- name/email as it was at that moment
  action       text        NOT NULL,                 -- '<entity>.<past-tense verb>', e.g. 'recipient.signed'
  subject_type text,
  subject_id   uuid,
  request_id   text,
  ip           inet,
  user_agent   text,
  data         jsonb       NOT NULL DEFAULT '{}',
  hash         bytea       NOT NULL CHECK (octet_length(hash) = 32),
  PRIMARY KEY (chain_id, seq)
);
CREATE INDEX audit_events_workspace_time ON audit_events (workspace_id, occurred_at DESC);
-- Triggers: BEFORE UPDATE OR DELETE (row) and BEFORE TRUNCATE (statement) raise an exception.
```

| Column | Purpose |
|---|---|
| `chain_kind`, `chain_id` | Which chain the entry belongs to; `chain_kind` says how to read `chain_id` (envelope vs workspace) |
| `seq` | Position in the chain; gaps reveal deletions |
| `workspace_id` | Tenant filter for the audit screen and isolation (equals `chain_id` on workspace chains; kept so every query filters the same way) |
| `occurred_at` | When it happened (printed on the certificate) |
| `actor_type`, `actor_id` | Who acted: a user, a signer (no account) or the system |
| `actor_label` | Snapshot of the name/email at that moment; names change later and signers are not users |
| `action` | What happened |
| `subject_type`, `subject_id` | What it happened to |
| `request_id` | Links the entry to server logs |
| `ip`, `user_agent` | E-signature attribution evidence; printed on the certificate |
| `data` | Action-specific details (e.g. decline reason, verification method) |
| `hash` | The fingerprint that makes tampering detectable |

**Removed after review:** the `audit_chain_heads` table (an advisory lock plus the last row does the same job),
a separate `id` (the primary key is `(chain_id, seq)`), and `prev_hash` (it duplicated the previous row's `hash`;
the verifier recomputes it and gaps reveal deletions).

### 4.7 Interface (sketch)

```python
class AuditChain:                                   # value object
    @staticmethod
    def envelope(workspace_id: UUID, envelope_id: UUID) -> "AuditChain": ...
    @staticmethod
    def workspace(workspace_id: UUID) -> "AuditChain": ...
    @staticmethod
    def system() -> "AuditChain": ...

def record(uow, *, chain: AuditChain, actor: Actor, action: str,
           subject: Subject | None = None, data: Mapping[str, JsonValue] | None = None) -> AuditEntry: ...
def verify(uow, chain_id: UUID) -> VerificationResult: ...      # ok, entries checked, first failure (seq, reason)
```

### 4.8 Tests that prove it

- Entries recorded and verified → chain intact.
- `UPDATE`, `DELETE`, `TRUNCATE` → rejected by the triggers.
- With triggers disabled in the test: change one entry's `data` → verify fails at that `seq`; delete one entry →
  verify reports the gap.
- 50 concurrent appends to one chain → `seq` 1–50 contiguous, chain verifies.
- Appends to different chains do not wait on each other's lock.
- Action rolled back → its audit entry does not exist.
- Canonical JSON is byte-identical before insert and after a database round trip.

---

## Topic 5 — File storage

### 5.1 What is stored

Every file in the product: uploaded agreements (PDF/DOCX), PDFs converted from DOCX, signer signature and initials
images, final signed PDFs with certificate, and later bulk-send spreadsheets. All are **immutable**.

### 5.2 Object keys: one layout for local disk and cloud object storage

Files are addressed by an **object key**, the native naming of S3-compatible storage. The same key is used by every
backend; only the backend's root differs.

```
workspaces/<workspace_id>/blobs/sha256/<h[0:2]>/<h[2:4]>/<h>
e.g. workspaces/0193f1c2-…/blobs/sha256/9f/2c/9f2c88e1…07a1e41a
```

| Backend | Root | Full location of that key |
|---|---|---|
| Local (now) | `BLOB_STORE_DIR` (default `./data/blobs`, repo-root relative) | `./data/blobs/workspaces/<ws>/blobs/sha256/9f/2c/9f2c…` |
| S3-compatible (cloud) | bucket `BLOB_STORE_BUCKET` (+ optional `BLOB_STORE_PREFIX`) | `s3://<bucket>/workspaces/<ws>/blobs/sha256/9f/2c/9f2c…` |

Why this layout follows common practice:
- **Tenant first** (`workspaces/<id>/`): per-tenant access policies, lifecycle and retention rules, usage
  reporting and deleting a tenant's data are all a single prefix operation in object storage.
- **Typed namespace** (`blobs/sha256/`): leaves room for other object families later without collisions, and states
  how names are derived.
- **Content address** (`sha256/<h>`): the name *is* the integrity check; identical content within a workspace is
  stored once; nothing can be overwritten with different content.
- **Two hex fan-out levels** (`9f/2c/`): keeps local directories small; in object storage, the random hex spreads
  keys across partitions.

### 5.3 Rules

1. **Deduplicated per workspace only.** The same file from two workspaces is stored twice: no cross-tenant
   "this file exists" signal, and a tenant's data can be deleted by prefix.
2. **Immutable.** Writes are put-if-absent; existing objects are never replaced.
3. **Atomic writes.** Local: stream into a temporary file under `BLOB_STORE_DIR/.tmp/`, hashing and enforcing the
   size limit while streaming, `fsync`, then `rename` into place. S3: a single `PUT` (atomic by definition) with
   `If-None-Match: *` (conditional write) after hashing to a spooled temporary file.
4. **No public URLs.** Reads go only through API endpoints that check permission and stream the bytes. (A later
   option for large downloads: short-lived pre-signed URLs issued after the same check.)
5. **No path tricks.** Keys are built only from a validated UUID and a 64-character lowercase hex digest, never from
   user input.
6. **No files table.** The owning module stores `sha256`, size and media type in its own table (e.g. a document
   version). Unreferenced objects left by rolled-back transactions are removed by a cleanup job in the hardening
   phase (objects older than 24 h that no module references).
7. **Limits:** 50 MB per upload, 1 MB per signature image (configuration).
8. **File type checks** (real PDF / DOCX by content, not by name or declared type) belong to the documents module
   (Phase 4). The store handles bytes only.
9. **Encryption at rest:** none for local storage (owner decision for this project); in the cloud, the bucket's
   default server-side encryption (SSE-S3 or SSE-KMS).

### 5.4 Configuration

```
BLOB_STORE_BACKEND=local            # local | s3
BLOB_STORE_DIR=./data/blobs         # local backend root (repo-root relative)
# s3 backend (later): BLOB_STORE_BUCKET, BLOB_STORE_PREFIX, BLOB_STORE_REGION,
#                     BLOB_STORE_ENDPOINT_URL (S3-compatible providers / MinIO), credentials from the environment
```

### 5.5 Interface

```python
@dataclass(frozen=True)
class BlobRef:
    workspace_id: UUID
    sha256: str            # 64 lowercase hex chars
    size: int

    @property
    def key(self) -> str:  # 'workspaces/<ws>/blobs/sha256/<h0:2>/<h2:4>/<h>'
        ...

class BlobStore(Protocol):
    def put(self, workspace_id: UUID, data: BinaryIO, *, max_bytes: int) -> BlobRef: ...  # raises TooLarge
    def open(self, ref: BlobRef) -> BinaryIO: ...                                       # raises NotFound
    def exists(self, ref: BlobRef) -> bool: ...

def blob_store_from_settings(settings) -> BlobStore: ...   # LocalBlobStore now; S3BlobStore later
```

Callers depend only on `BlobStore` and `BlobRef`; switching to the cloud is a configuration change plus the S3
implementation, with no change to modules.

### 5.6 Tests that prove it

One **contract test suite** written against the `BlobStore` interface, run against the local backend now and against
the S3 backend (MinIO in Docker) when it is added:
- put then open returns identical bytes; `sha256` and `size` are correct; the key matches the layout.
- Same bytes twice in one workspace → one object; in two workspaces → two objects.
- Over `max_bytes` → `TooLarge`, and nothing is left behind.
- Interrupted write (simulated crash) → no partial object at the final key.
- Invalid workspace id or digest → rejected before any filesystem or network access.

**Complexity:** put and open are O(size) (one streaming pass with hashing); lookup by key is O(1).

---

## Topic 6 — Configuration and path resolution

### 6.1 Scope

**Configuration** is how this installation runs: database address, secrets, Gotenberg location, AI key, email
account, storage backend. It comes from environment variables or `.env` and changes require a restart.
**Business settings** (a project's reminder interval, POC emails, countersigners) are data in tables, edited in the
console — never configuration.

### 6.2 Rules

1. **One settings object**, loaded once per process, typed and read-only (`pydantic-settings`). API, worker and CLI
   load it identically.
2. **Precedence** (twelve-factor): process environment variables > `.env` file > defaults in code. In Docker, compose
   provides environment variables, so the same code runs unchanged.
3. **Repository root:**
   - `SIGNORA_ROOT` if set (container images set `/app`);
   - otherwise derived from the package location (`apps/api/src/signora/` → four levels up) and confirmed by the
     marker file `.env.example`;
   - otherwise startup fails with an explanation.
   `.env` is read from the root, never from the working directory, and every relative path setting (e.g.
   `BLOB_STORE_DIR=./data/blobs`) resolves against the root.
4. **Fail fast with every problem at once.** Startup validates all values and stops with one message listing every
   violation, for example: `SECRET_KEY` shorter than 32 characters, empty `POSTGRES_PASSWORD`, port outside
   1–65535, unknown `APP_ENV`, non-`https` `PUBLIC_BASE_URL` in production.
5. **Core vs integrations.** Core settings (app, database, storage, Gotenberg, signing defaults, worker) are required
   to start. Integration settings (AI, email, Stripe) may be empty when `APP_ENV=development`: using an unconfigured
   integration raises a clear `IntegrationNotConfigured` error, and the readiness endpoint reports it as
   "not configured". With `APP_ENV=production` every integration is required at startup.
6. **Secrets** are `SecretStr`: shown as `**********` in logs, errors and `repr`; the raw value is read only where
   it is used.
7. **Grouped settings, least privilege.** Settings are grouped by area and each module receives only its own group
   (dependency injection), so e.g. the email module never sees the database password, and tests pass small fake
   groups.
8. **No duplicated values.** Derived values (the database URL, Gotenberg base URL) are computed from their parts and
   never stored as a second variable.
9. **`.env.example` is the single list of variables.** A test fails when a setting exists in code but not in
   `.env.example`, or the reverse.

### 6.3 Groups and variables

| Group | Variables (from `.env`) | Required |
|---|---|---|
| `app` | `APP_ENV`, `PUBLIC_BASE_URL`, `SECRET_KEY`, `LOG_LEVEL` | core |
| `db` | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | core |
| `blob_store` | `BLOB_STORE_BACKEND`, `BLOB_STORE_DIR` (+ S3 variables later) | core |
| `gotenberg` | `GOTENBERG_HOST`, `GOTENBERG_PORT` | core |
| `signing` | `SIGNING_OTP_TTL_MINUTES`, `SIGNING_OTP_MAX_ATTEMPTS`, `SIGNER_SESSION_MINUTES`, `DEFAULT_REMINDER_INTERVAL_HOURS`, `DEFAULT_MAX_REMINDERS`, `DEFAULT_EXPIRY_DAYS` | core (defaults) |
| `worker` | `WORKER_CONCURRENCY` | core (default 8) |
| `ai` | `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, `AI_REASONING_EFFORT`, `AI_WHOLE_DOC_MAX_TOKENS`, `AI_MAX_CONCURRENCY` | integration |
| `email` | `EMAIL_PROVIDER`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM_ADDRESS`, `EMAIL_FROM_NAME`, `EMAIL_DAILY_LIMIT` | integration |
| `stripe` | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | integration (later feature) |

`.env` keeps its flat names; they are mapped into these groups. New in Phase 1: `BLOB_STORE_BACKEND` (default
`local`) and `WORKER_CONCURRENCY` (default 8) are added to `.env.example`.

### 6.4 Interface (sketch)

```python
class DatabaseSettings(BaseModel):
    host: str; port: int; user: str; password: SecretStr; name: str
    @property
    def url(self) -> str: ...                 # built from parts, never stored

class Settings(BaseSettings):                 # env > .env (at repo root) > defaults
    app: AppSettings; db: DatabaseSettings; blob_store: BlobStoreSettings
    gotenberg: GotenbergSettings; signing: SigningSettings; worker: WorkerSettings
    ai: AISettings; email: EmailSettings; stripe: StripeSettings

def repo_root() -> Path: ...                  # SIGNORA_ROOT, else derived + marker check
def get_settings() -> Settings: ...           # loaded once, cached, read-only
```

### 6.5 Tests that prove it

- API-style and worker-style processes started from the repo root, from `apps/api` and from `/tmp` resolve the same
  root, `.env` and `BLOB_STORE_DIR`.
- `SIGNORA_ROOT` overrides derivation; a missing marker fails with a clear message.
- An environment variable overrides the same key in `.env`.
- Several invalid values → one error listing all of them.
- Development with empty `AI_API_KEY` starts; production with it empty fails at startup.
- `SecretStr` values never appear in `repr`, logs or error output.
- Every settings field is in `.env.example` and every `.env.example` variable maps to a field.

---

## Topic 7 — Errors, logging and health endpoints

### 7.1 Error responses

Every error uses RFC 9457 problem details (`Content-Type: application/problem+json`):

```json
{
  "type": "/problems/validation-failed",
  "title": "Some fields are invalid",
  "status": 422,
  "detail": "2 fields need attention",
  "code": "validation-failed",
  "instance": "/api/v1/projects",
  "request_id": "7f3c…",
  "errors": [{ "field": "poc_emails[0]", "message": "Not a valid email" }]
}
```

- `code` — stable machine-readable name; the frontend switches on it (never on `title` text).
- `errors` — per-field messages so forms can show each one under its field (validation errors only).
- `request_id` — links what the user saw to the server logs.

Modules raise domain errors from `kernel/errors`; one exception handler maps them to responses. No module builds
error responses itself.

| Error | Status | When |
|---|---|---|
| `ValidationFailed` | 422 | Invalid input; FastAPI/pydantic validation errors are converted to this shape |
| `Unauthenticated` | 401 | No session or session expired |
| `PermissionDenied` | 403 | Authenticated but lacking the required access on this project |
| `NotFound` | 404 | Does not exist **or belongs to another workspace** |
| `Conflict` | 409 | Wrong state for the action (e.g. version already approved) |
| `IdempotencyKeyMissing` | 400 | Topic 3 |
| `IdempotencyKeyReused` | 422 | Topic 3 |
| `RequestInProgress` | 409 + `Retry-After` | Topic 3 |
| `PayloadTooLarge` | 413 | Over the configured size limit |
| `RateLimited` | 429 + `Retry-After` | Too many attempts (e.g. OTP) |
| `IntegrationNotConfigured` | 503 | AI, email or Stripe not configured |
| any unexpected exception | 500 | Generic title and `request_id` only; never stack traces or internal details (those go to the log) |

**Tenant rule:** a resource of another workspace is reported as `404`, never `403`, so its existence is not revealed.

### 7.2 Logging

- Structured JSON, one event per line, to stdout (collected by Docker). With `APP_ENV=development` on a terminal,
  a readable console format is used instead.
- Every line: `ts` (UTC), `level`, `event`, `request_id`; plus `workspace_id`, `user_id`, `job_id`, `job_kind` when
  known (bound through context, not passed by hand).
- One access line per request: method, **route template** (e.g. `/s/{token}`, never the raw path, because signing
  links carry secret tokens), status, duration in ms.
- **Request id:** an incoming `X-Request-ID` is accepted only if it is a well-formed id (Caddy sets one); otherwise a
  new one is generated. It is returned in the `X-Request-ID` response header, included in error bodies, and stored in
  the metadata of every job enqueued by that request, so a job's logs link back to the action that caused it.
- **Never logged:** request or response bodies; passwords, tokens, OTP codes, cookies, `Authorization` headers;
  signature images. A redaction processor masks any field whose name matches
  `password|secret|token|otp|code|cookie|authorization` as a safety net.
- **Personal data minimised:** logs carry ids, not names or email addresses. (The audit log keeps names
  intentionally, as evidence.)
- Levels: `INFO` by default (`LOG_LEVEL`), `DEBUG` locally when needed.

### 7.3 Health and metadata endpoints

| Endpoint | Answers | Checks | Used by |
|---|---|---|---|
| `GET /api/v1/health/live` | Is the process running? | Nothing external; 200 whenever it can respond | Docker restart policy |
| `GET /api/v1/health/ready` | Can it serve traffic? | Database (`SELECT 1`), migrations at head, blob store writable, Gotenberg `/health`; AI, email and Stripe reported as configured or not (informational in development) | Docker, Caddy, operators |
| `GET /api/v1/meta` | Which build is running? | — | UI footer, bug reports |

- Each readiness check has a 2-second timeout. `200` when every core check passes, otherwise `503`.
- **Public vs local detail:** requests from outside (through Funnel) receive only `{"status":"ok"}` or
  `{"status":"unavailable"}`. The per-check breakdown (component, status, duration, message) is returned only to
  requests from the loopback address or the Docker networks.
- `/meta` returns `{"version": "<package version>", "commit": "<short git sha>"}`; the commit is baked in at build time
  (`SIGNORA_COMMIT`), falling back to `"dev"`.

### 7.4 Worker health

The worker serves no HTTP. It touches a heartbeat file every 10 seconds; the container healthcheck fails if the
file is older than 30 seconds, and Docker restarts it. No extra table or port.

### 7.5 Tests that prove it

- Each domain error maps to its status and `code`; FastAPI validation errors come out in the same shape with
  per-field `errors`.
- An unexpected exception → 500 with `request_id` only; the log line contains the stack trace.
- Cross-workspace access → 404.
- Redaction masks secret-looking keys; the access log uses route templates (a `/s/<token>` request logs `/s/{token}`).
- A request id appears in the response header, the error body, the logs, and the jobs enqueued by that request.
- `/health/ready` returns 503 naming the failed check when the database or Gotenberg is down (local request), and
  only `{"status":"unavailable"}` for a non-local request.
- Worker heartbeat goes stale when the loop is blocked → healthcheck fails.

---

## Topic 8 — Frontend shell

### 8.1 Versions and dependency age

Same rule as the backend: only releases published at least 14 days earlier. Enforced by pnpm with
`minimumReleaseAge: 20160` (minutes) in `pnpm-workspace.yaml`, mirroring `exclude-newer` in `apps/api/pyproject.toml`.

| Package | Version | Published |
|---|---|---|
| next | 16.4.3 | 2026-10-23 |
| react, react-dom | 19.3.1 | 2026-10-14 |
| typescript | 7.0.2 | 2026-07-08 |
| @tanstack/react-query | 5.104.5 | 2026-10-19 |
| openapi-typescript / openapi-fetch | 7.13.0 / 0.17.0 | 2026-02-11 |
| eslint / eslint-plugin-boundaries | 10.13.0 / 7.3.0 | 2026-10-16 / 2026-10-23 |
| vitest | 5.0.5 | 2026-10-15 |
| pnpm (`packageManager`) | 12.15.0 | 2026-10-21 |

### 8.2 Role of Next.js

- Next.js renders the UI only: **no business logic and no API routes**. All data comes from the FastAPI backend.
- The browser calls `/api/...` on the same origin; Caddy routes it to FastAPI. Session cookies work without
  cross-site configuration and there is a single public origin.
- Production build: Next.js `standalone` output, run as a small Node server behind Caddy. Development: `next dev`
  with a rewrite of `/api/*` to the local API.

### 8.3 Structure (`apps/web/src/`)

```
app/                 routes only (thin): (public)/…, (console)/…, s/… (signer), dev/ui (gallery, development only)
features/<module>/   one folder per business module, filled in its own phase
shared/
  ui/                tokens.css + design-system components (single source of styling)
  api/               typed client, query client setup, useIdempotentAction (topic 3.6)
  lib/               small pure helpers (formatting, etc.)
packages/contracts/  types generated from the API's OpenAPI document (never edited by hand)
```

Boundary rule (`eslint-plugin-boundaries`): `features/*` may import `shared/*` and `packages/contracts`, never
another feature's internals; `shared/*` never imports `features/*`; `app/*` composes features.

### 8.4 Styling

- Plain CSS: the prototype's tokens in `shared/ui/tokens.css` (single source) plus one CSS Module per component,
  ported line by line from `docs/design-system/prototype.html`. No Tailwind.
- Fonts via `next/font/google` (downloaded at build time, self-hosted): Cormorant Garamond 300/400/500 + italic,
  Source Code Pro, Inter Tight (logo). Body text uses the system UI font, as in the prototype.
- Dark only (as the prototype). Minimum width 360 px. Visible focus, labelled controls, `prefers-reduced-motion`
  respected.

### 8.5 Talking to the API

- `openapi-fetch` typed with the generated contract types: an API change without a frontend update fails the build.
- TanStack Query for reads, with `refetchOnReconnect` and `refetchOnWindowFocus` (topic 3.6).
- **`useIdempotentAction`** — the one helper every mutating action uses: creates and keeps the idempotency key
  (also in `sessionStorage`), shows "Sending…" / "Connection lost — retrying…", retries on reconnect and on backoff,
  honours `409 Retry-After`, and reuses the key when pressed again.
- Errors: the problem `code` maps to a user-facing message; unexpected errors show the `request_id`.

### 8.6 Phase 1 components

Button (primary ghost, quiet, quiet-destructive; loading state; trailing arrow), text-link button, TextField and
TextArea (underline style with label, hint, error), Select (the prototype's custom keyboard-accessible listbox),
Checkbox, Radio, TablePanel, StatusPill (all ten states with the prototype's dot colors), Notice (info, warning),
Toast, Tabs, TopBar, AppShell (logo, workspace name, navigation), typography (Eyebrow, headings), MetricTile.

Screen-specific components arrive with their feature (project cards, filter bar, date picker, timeline, drop zone,
PDF canvas, signature pad).

**Visible result of Phase 1:** `/` renders the shell and shows `/api/v1/meta` (proves browser → Caddy → API);
`/dev/ui` (development only) shows every component for side-by-side comparison with the prototype.

### 8.7 Tests

Vitest + Testing Library: component behaviour (Select keyboard navigation, Button loading state, Toast) and
`useIdempotentAction` (key reused on retry and on second press, retry on reconnect, `409` honoured, key discarded only
after a definite response). Browser end-to-end tests (Playwright) come in the hardening phase.

---

## Topic 9 — Quality gate and runtime

### 9.1 `make check` (the local gate before every merge; no hosted CI)

| Area | Command | Fails when |
|---|---|---|
| Python format + lint | `ruff format --check`, `ruff check` | Style or lint violation |
| Python types | `mypy --strict src` | Any type error |
| Module boundaries | `lint-imports` | A boundary contract (9.2) is broken |
| Python tests | `pytest` (incl. `.env.example` sync test) | Any failure; coverage below 85 % for `kernel` and `modules/audit` |
| Contracts | `make contracts` then `git diff --exit-code packages/contracts` | Generated API types differ from the committed ones |
| TypeScript | `pnpm -r typecheck` (`tsc --noEmit`) | Any type error |
| Frontend lint | `pnpm -r lint` (ESLint incl. boundaries) | Lint or boundary violation |
| Frontend tests | `pnpm -r test` (Vitest) | Any failure |
| Frontend build | `pnpm --filter web build` | Build error |

Other targets: `make dev` (infra + API with reload + worker + `next dev`), `make up-app` (full stack in Docker),
`make migrate`, `make contracts`, `make test`, `make lint`.

### 9.2 Import-boundary contracts (`import-linter`)

1. **Layers:** `signora.entrypoints` → `signora.modules` → `signora.kernel` (no upward imports).
2. **Public interfaces only:** a module may import another module only through its package root
   (`signora.modules.audit`), never its internals (`signora.modules.audit.repository`).
3. **Leaf modules** (`detection`, `rendering`, `verification`, `notifications`, `audit`) import only `signora.kernel`.
4. **Pure domain:** `*.domain` modules import neither FastAPI nor SQLAlchemy.

In Phase 1 only `kernel` and `modules/audit` exist; the contracts are written for the full module map so later
phases inherit them.

### 9.3 Test database

A dedicated `signora_test` database on the compose Postgres, recreated at the start of each test session and migrated
to head. Ordinary tests run inside a transaction that is rolled back. Concurrency tests (job claiming, audit appends,
idempotency) need real commits; they use unique ids (fresh chain ids, job kinds), so they never collide and the
session-level recreate cleans up — this matters because the audit triggers forbid deleting rows.

### 9.4 Container images

- `apps/api/Dockerfile`: multi-stage; `uv sync --frozen --no-dev`; non-root user; `SIGNORA_ROOT=/app`;
  `SIGNORA_COMMIT` build argument. **One image** for API, worker and migrations (different commands).
- `apps/web/Dockerfile`: multi-stage Next.js `standalone` build; non-root user.

### 9.5 Compose services

| Service | Image / command | Networks | Published | Notes |
|---|---|---|---|---|
| `postgres` | postgres 18.4 | app | `127.0.0.1:${POSTGRES_PORT}` | existing |
| `gotenberg` | gotenberg 8.40.0 | convert (internal) | — | existing |
| `gotenberg-gateway` | socat | app, convert | `127.0.0.1:${GOTENBERG_PORT}` | existing |
| `migrate` | api image, `signora migrate` | app | — | one-shot; `api` and `worker` start only after it succeeds |
| `api` | api image, uvicorn | app, convert | — | overrides `POSTGRES_HOST=postgres`, `POSTGRES_PORT=5432`, `GOTENBERG_HOST=gotenberg`, `GOTENBERG_PORT=3000`; blob volume |
| `worker` | api image, `signora worker` | app, convert | — | heartbeat-file healthcheck (topic 7.4); blob volume |
| `web` | web image | app | — | Next.js standalone |
| `caddy` | caddy (pinned) | app | `127.0.0.1:3100` | Funnel target; `/api/*` → `api`, everything else → `web` |

Compose profiles: `make up` starts infrastructure only (for host development); `make up-app` starts the whole stack
behind Caddy, which is what the public Funnel URL serves.

### 9.6 Caddy

- Routes `/api/*` to the API and everything else to the web server.
- Sets `X-Request-ID` when absent; JSON access logs.
- Request body limit slightly above the upload limit (55 MB).
- Security headers on every response: `Strict-Transport-Security` (the public origin is HTTPS via Funnel),
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, a minimal
  `Permissions-Policy`. API responses also get `Content-Security-Policy: default-src 'none'`; HTML pages get a
  nonce-based CSP set by Next.js middleware. Signer-specific headers (`noindex`) come with Phase 8.

### 9.7 Development ports

Host ports 3000, 5432–5434 and others are already used on this machine. Development servers use configurable ports
chosen to be free: `API_DEV_PORT` (default 8100) and `WEB_DEV_PORT` (default 3200); `next dev` rewrites `/api/*` to
the API dev port.

---

## Topic 10 — Requirements, decisions and tasks

### 10.1 Functional requirements (backbone)

| ID | Requirement |
|---|---|
| FR-B1 | Configuration loads once, resolves the repository root and relative paths independently of the working directory, and fails at startup listing every invalid value (topic 6). |
| FR-B2 | Schema changes are applied with Alembic migrations; the API and worker refuse to report ready unless migrations are at head. |
| FR-B3 | Jobs can be enqueued inside a business transaction, are delivered at least once and claimed by exactly one worker at a time, retried with backoff, dead-lettered after the per-kind limit, and reclaimed after a lease expires (topics 1–2). |
| FR-B4 | Domain events fan out to every registered subscriber as independent jobs (topic 1.5). |
| FR-B5 | Create endpoints honour `Idempotency-Key` per the server contract (topic 3). |
| FR-B6 | Files are stored immutably under tenant-first object keys behind a backend-neutral interface (topic 5). |
| FR-B7 | Audit entries are appended to per-envelope, per-workspace or system hash chains in the action's transaction, cannot be updated or deleted, and chains can be verified (topic 4). |
| FR-B8 | All errors use RFC 9457 problem details with stable codes; logs are structured and redacted; live, ready and meta endpoints exist (topic 7). |
| FR-B9 | The web app renders the design-system shell, the component gallery, and reads `/api/v1/meta` through Caddy (topic 8). |
| FR-B10 | `make check` runs every gate in topic 9.1 and fails on any violation. |

### 10.2 Non-functional requirements (backbone)

| ID | Target |
|---|---|
| NFR-B1 | Job pickup ≤ 1 s after the enqueuing transaction commits (LISTEN/NOTIFY), ≤ 5 s worst case (poll). |
| NFR-B2 | Enqueue adds ≤ 5 ms to a transaction; audit append ≤ 10 ms p95 under 50 concurrent appends to one chain. |
| NFR-B3 | Health and meta endpoints respond ≤ 50 ms p95 locally; readiness ≤ 2.5 s worst case (2 s per-check timeout, run concurrently). |
| NFR-B4 | Startup with invalid configuration fails within 2 s with a complete list of problems. |
| NFR-B5 | Test coverage ≥ 85 % for `kernel` and `modules/audit`; `make check` completes in ≤ 5 minutes on the development machine. |
| NFR-B6 | No secret, token, OTP or request body appears in logs (asserted by tests). |
| NFR-B7 | Containers run as non-root; only Caddy (3100), Postgres and the Gotenberg gateway are published, and only on 127.0.0.1. |

### 10.3 Architecture decisions recorded in this phase

| ADR | Decision | Main reason |
|---|---|---|
| B-1 | Synchronous SQLAlchemy 2 + psycopg 3; async FastAPI handlers call it through the thread pool | Simpler code and tests; slow work runs in the worker anyway |
| B-2 | UUIDv7 primary keys (Postgres 18 `uuidv7()`), exposed as plain UUID strings; the UI shortens them for display | Time-ordered ids with good index locality, no extra encoding layer |
| B-3 | Postgres job queue with `SKIP LOCKED`, leases and LISTEN/NOTIFY; events as fan-out jobs; no Redis/Celery | One less service, transactional enqueue, durable across restarts (topics 1–2) |
| B-4 | Idempotency key held inside the action's transaction; status codes per the IETF draft and Stripe | Database serializes duplicates; standard client behaviour (topic 3) |
| B-5 | Audit hash chains per envelope and per workspace, plus a system chain; written synchronously | No cross-envelope contention; certificate = one chain; entry cannot be lost (topic 4) |
| B-6 | Tenant-first, content-addressed object keys shared by local and S3 backends | Cloud move is configuration only; per-tenant prefix operations (topic 5) |
| B-7 | Tenant isolation enforced in the data-access layer from Phase 2; Postgres row-level security added in the hardening phase | Fast delivery now, defence in depth before release |
| B-8 | RFC 9457 errors with stable codes; other-tenant resources reported as 404 | One error shape for all clients; no existence leaks (topic 7) |
| B-9 | Next.js renders UI only; plain CSS tokens ported from the prototype; typed client generated from OpenAPI | No business logic on the client tier; faithful design port; one API contract (topic 8) |
| B-10 | Local quality gate (`make check`) instead of hosted CI, plus manual testing before merge | Owner decision (topic 9) |

### 10.4 Tasks (one commit each)

| # | Task | Status | Evidence |
|---|---|---|---|
| 1.1 | Backbone LLD (this document) | done | topics 1–10 |
| 1.2 | `kernel/config`: settings groups, repo-root resolution, validation, `.env.example` sync test | todo | — |
| 1.3 | `kernel/db`: engine, unit of work, Alembic setup, naming conventions; migration 0001 (`jobs`, `idempotency_keys`, `audit_events` + triggers) | todo | — |
| 1.4 | `kernel/errors`, `kernel/logging`, request id; API app factory; health and meta endpoints | todo | — |
| 1.5 | `kernel/jobs`: enqueue, worker loop, leases, backoff, dead jobs, LISTEN/NOTIFY, housekeeping sweep | todo | — |
| 1.6 | `kernel/events`: publish/subscribe over jobs | todo | — |
| 1.7 | `kernel/idempotency`: dependency, transaction-held key, 400/409/422 handling | todo | — |
| 1.8 | `kernel/blobstore`: `BlobStore` interface, local backend, contract test suite | todo | — |
| 1.9 | `modules/audit`: chains, record, verify, CLI `signora audit verify` | todo | — |
| 1.10 | Import-linter contracts, Makefile targets, `make check` | todo | — |
| 1.11 | Web: pnpm workspace, Next.js app, tokens, Phase 1 components, AppShell, `/` and `/dev/ui`, `useIdempotentAction` | todo | — |
| 1.12 | `packages/contracts`: OpenAPI export + generated types + drift check | todo | — |
| 1.13 | Dockerfiles, compose `migrate`/`api`/`worker`/`web`/`caddy`, Caddyfile; shell live on the Funnel URL | todo | — |
