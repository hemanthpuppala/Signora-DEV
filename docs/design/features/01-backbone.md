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
| 3 | Idempotency: server contract and schema | **agreed** (2026-11-07); client reconnect behaviour (§3.6) proposed, pending confirmation |
| 4 | Audit log: chain scope, system events, schema | open — proposal on the table: one chain per envelope plus one per workspace |
| 5 | File storage | open |
| 6 | Configuration and path resolution | open |
| 7 | Errors, logging, health APIs | open |
| 8 | Frontend shell | open |
| 9 | Quality gate (`make check`) and runtime (compose, Caddy) | open |
| 10 | Phase 1 FRs, NFRs, ADRs (summary) | open |

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

### 3.6 Client behaviour after a network blip (proposed, pending confirmation)

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
