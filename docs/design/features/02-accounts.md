# Phase 2 — Accounts & workspaces (LLD)

Parent design: [`../signora-platform.md`](../signora-platform.md) · Backbone: [`01-backbone.md`](01-backbone.md) ·
Branch: `phase-2/accounts`

Phase 2 lets a company create a workspace, lets people sign in, and lets the workspace creator bring in teammates.
It also brings forward the smallest email delivery the auth flows need. Every decision below was agreed topic by
topic with the owner on 2026-11-07; numbers in **bold** are configuration (`.env`), not code.

## Topic status

| # | Topic | Status |
|---|---|---|
| 1 | Sign-up with email verification | **agreed** |
| 1a | Email delivery (`notifications` module) | **agreed** |
| 2 | Password reset | **agreed** |
| 3 | Password rules and hashing | **agreed** |
| 4 | Sessions and CSRF | **agreed** |
| 5 | One workspace per user; tenant isolation | **agreed** |
| 6 | Invites | **agreed** |
| 7 | Log-in and throttling | **agreed** |
| 8 | Access rules (roles as data), members, account settings | **agreed** |

---

## Problem statement

Signora is multi-tenant: each company (a **workspace**) keeps its documents, envelopes and people apart from every
other company. Phase 2 provides the identity layer every later feature relies on: who the caller is (sessions), which
company they belong to (tenant isolation), and what they may do (permissions). It must resist the usual attacks on
auth flows (account enumeration, password guessing, CSRF, session theft) without making sign-up or log-in awkward.

## Functional requirements

| # | Requirement |
|---|---|
| FR-A1 | A visitor signs up with only an email. The response is the same whether or not the email is registered. A new email receives a verification link; a registered one receives a "you already have an account" email. |
| FR-A2 | Opening a valid sign-up link lets the visitor set workspace name, their name and password. This creates the workspace, its two system roles and the creator's user, then signs them in. |
| FR-A3 | A user logs in with email and password and logs out. Unknown email and wrong password give the same error. |
| FR-A4 | A user who forgot their password requests a reset link (same response for any email) and sets a new password with it. All their sessions end. |
| FR-A5 | A signed-in user changes their own name and password (password change needs the current one and ends their other sessions). |
| FR-A6 | Users with `members.manage` (by default only the creator) see the People screen: members, roles, pending invites. |
| FR-A7 | They invite by email with a role, resend and revoke invites, change a member's role and remove a member. |
| FR-A8 | An invitee accepts with name and password and is signed in. Inviting an email that belongs to another company looks identical to the inviter. |
| FR-A9 | Users with `members.directory` (by default read/write) can list active colleagues (id, name, email) for pickers. |
| FR-A10 | Users with `workspace.rename` (by default read/write) rename the workspace. |
| FR-A11 | No user can read or change another workspace's data; another workspace's ids answer 404. |
| FR-A12 | The creator always has every permission and cannot be demoted or removed; nobody removes themselves. |
| FR-A13 | Workspace actions (created, member joined/removed/restored, role changed, invite created/revoked, renamed) are audited in the workspace chain. Account security events (log-ins, failures, password reset/change) go to the security log. |
| FR-A14 | All auth emails are delivered through the `notifications` module (SendGrid first, Gmail SMTP alternative, Mailpit in development). |

## Non-functional requirements

| # | Requirement | Threshold |
|---|---|---|
| NFR-A1 | Enumeration resistance | Sign-up, forgot-password and invite creation return the same status, body and (within noise) time for registered and unregistered emails; the lookups run in background jobs. |
| NFR-A2 | Password storage | Argon2id (RFC 9106 low-memory profile: 64 MiB, t=3, p=4); hashes upgraded on log-in when parameters change. |
| NFR-A3 | Tokens | All link and session tokens are 256-bit random (`secrets.token_urlsafe(32)`), stored only as SHA-256; link tokens travel in the URL fragment so they never reach server logs. |
| NFR-A4 | Session check cost | One indexed query per authenticated request; `last_seen_at` written at most every **5 minutes** per session. |
| NFR-A5 | Brute-force resistance | Per email: after **5** failures, waits double from 1 s to a **15 min** cap. Per IP: **100** failures per **15 min**. No account lockout. |
| NFR-A6 | Rate-limit memory | In-memory limiter bounded to **100 000** keys (least recently used evicted); swappable for Redis behind one interface. |
| NFR-A7 | Email delivery | At-least-once; transient failures retried with job backoff; permanent failures recorded, not retried; bodies purged once the message is final. |
| NFR-A8 | Auth endpoints latency | p95 ≤ 150 ms locally except log-in and password-setting endpoints, which are dominated by one Argon2id hash (~50–100 ms). |
| NFR-A9 | Tenant isolation | Every repository query takes the workspace id from the session; a cross-workspace test exists for every endpoint with an id in its path. |

## Glossary

- **Workspace**: one company's account; every business row carries `workspace_id`.
- **User**: one person, identified to people by email (unique across Signora) and internally by a UUID. Belongs to
  exactly one workspace (owner decision: one email, one company; no domain checks).
- **Creator**: the user who created the workspace (`workspaces.created_by`).
- **Permission**: a named capability the code checks (`members.manage`). The catalogue is code.
- **Role**: a named set of permissions, stored as data per workspace. Every workspace starts with *Read* and
  *Read/write*.

---

## Topic 1 — Sign-up with email verification

### 1.1 Flow (email first)

1. **Request** — `POST /api/v1/auth/signup {email}` → always `202 {"status": "check_email"}`.
   - The handler normalises the email, applies the email limits (**60 s** cooldown, **5 per hour**, plus the IP
     limit), and enqueues a `identity.signup_request` job with the email. It does no database lookup, so the
     response cannot differ by account existence, even in timing (NFR-A1).
   - When a limit is exceeded the response is still `202` and no job is queued (an attacker learns nothing; a real
     user retries a minute later).
   - The job: if a user with that email exists → queue the *already registered* email (links to log-in and
     forgot-password). Otherwise → create an `email_tokens` row (`purpose=signup`, **24 h**) and queue the
     *verify your email* email with `PUBLIC_BASE_URL/signup/verify#<token>`.
2. **Open** — the page reads the token from the fragment and calls `POST /api/v1/auth/signup/verify {token}` →
   `200 {"email": ...}` or `410 link-expired` (unknown, used and expired tokens look the same).
3. **Complete** — `POST /api/v1/auth/signup/complete {token, workspace_name, name, password}` with an
   `Idempotency-Key`. One transaction:
   - lock the token row (`FOR UPDATE`); it must be unused and unexpired (`410 link-expired` otherwise);
   - if a user with the email now exists (two links used at nearly the same time) → `409 account-exists`;
   - validate the password (topic 3) and hash it;
   - create the workspace, its two system roles, and the user with the *Read/write* role; set
     `workspaces.created_by`;
   - mark every unused signup token for that email used;
   - audit `workspace.created` and `member.joined` (workspace chain).
   - Response `201 {"email": ...}`. **No session is created here** (see 1.2).
4. **Sign in** — the page immediately calls `POST /auth/login` with the email and the password it still holds.

### 1.2 Why completion does not set the session cookie

Completion is a create action, so it uses an idempotency key and its response may be replayed. A replay would have to
store the session cookie with the key, putting a live secret in `idempotency_keys`. Instead completion returns
`201` without a session, and the page logs in normally; a retried completion replays `201` and the log-in follows.

### 1.3 Edge cases

- Several links requested: every unexpired unused link works; completion uses them all up.
- The visitor has a pending invite elsewhere: sign-up creates their own workspace; the invite then fails on accept
  with "already belongs to another workspace" (topic 6).
- Email delivery failing: the email job retries with backoff (NFR-A7); the visitor may request again after 60 s.

---

## Topic 1a — Email delivery (`notifications` module)

### 1a.1 Decision

One in-app module owns delivery; callers own content. There is no HTTP endpoint for sending (it would be an open
relay). This is the usual "notification service" split (delivery, retries, suppression and logs in one place;
templates with each feature), kept in-process per the modular-monolith ADR.

### 1a.2 Interface

```python
# signora.modules.notifications (public interface)
def send_email(
    uow: UnitOfWork,
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    category: str,                 # e.g. "auth.signup_verify"; for logs and metrics
    workspace_id: uuid.UUID | None = None,
    dedupe_key: str | None = None, # same key → queued once
) -> uuid.UUID | None: ...          # message id, or None when deduplicated

def render_layout(*, heading: str, paragraphs: Sequence[str], action: EmailAction | None) -> RenderedEmail
```

`send_email` inserts an `email_messages` row and enqueues the `notifications.send_email` job **in the caller's
transaction**: if the caller rolls back, nothing is sent. `render_layout` gives every email the same plain,
accessible layout (text and HTML parts, escaped by Jinja2 autoescape).

### 1a.3 Delivery job and providers

- `EMAIL_PROVIDER` selects the transport: `sendgrid` (v3 `POST /v3/mail/send`), `smtp` (Gmail: STARTTLS on 587 with
  an app password) or `mailpit` (development capture: SMTP on 1025, no TLS, no auth).
- Outcomes:
  - accepted → `status=sent`, provider message id stored, body purged;
  - **transient** (timeout, connection error, HTTP 429/5xx, SMTP 4xx) → raise, the job retries with backoff (max
    **8** attempts), then `status=failed`;
  - **permanent** (HTTP 400/401/403/413, SMTP 5xx recipient refused) → `status=failed` at once, body purged, error
    logged (401/403 at error level: a configuration problem).
- `EMAIL_DAILY_LIMIT` (**450**) is checked before each send (count of `sent` in the last 24 h); over the limit the
  job is retried later, so Gmail's daily cap is never exceeded.
- Known limit: a crash after the provider accepted a message but before `sent` is recorded can deliver it twice.
  Every email system has this window; it is documented, not hidden.
- Privacy: bodies hold sign-in links, so logs carry only the message id, category, provider and outcome; the body is
  purged when the message reaches `sent` or `failed`.

### 1a.4 Schema — `email_messages`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, `uuidv7()` | PK |
| `workspace_id` | uuid null | FK `workspaces` once it exists (auth emails before sign-up have none) |
| `category` | text | |
| `to_address` | text | |
| `subject` | text | |
| `text_body`, `html_body` | text null | purged on `sent`/`failed` |
| `status` | text | `queued` \| `sent` \| `failed` (check constraint) |
| `provider`, `provider_message_id` | text null | |
| `attempts` | int | |
| `last_error` | text null | truncated to 2 000 chars |
| `dedupe_key` | text null | unique |
| `created_at`, `sent_at`, `failed_at` | timestamptz | |

Index: `(status, created_at)`. Retention: the housekeeping sweep deletes `sent` rows after **30 days**.

---

## Topic 2 — Password reset

1. **Request** — `POST /api/v1/auth/password/forgot {email}` → always `202`. Limits as sign-up. Enqueues
   `identity.password_reset_request`; the job sends a reset email only to an **active** user (unknown and deactivated
   emails get nothing, per OWASP). UI text: "If an account exists for this email, you'll receive an email."
2. **Open** — `PUBLIC_BASE_URL/reset-password#<token>` → `POST /auth/password/reset/verify {token}` →
   `200 {"email": ...}` or `410 link-expired`.
3. **Set** — `POST /auth/password/reset {token, password}`. One transaction: lock the token (unused, unexpired,
   **30 min**), validate and hash the password, mark every reset token of the user used, **delete all the user's
   sessions**, queue the *password changed* email, write `auth.password_reset` to the security log.
4. The page sends the user to log-in with the email filled in (no automatic log-in, per OWASP).

---

## Topic 3 — Password rules and hashing

- **12–128 characters** after Unicode NFKC normalisation; any characters, including spaces; no composition rules;
  no forced rotation.
- Rejected when on the bundled list of the **100 000** most common passwords (SecLists, MIT licence), checked
  case-insensitively from an in-memory set (O(1)). Personal-information checks: none (owner decision).
- Have I Been Pwned: deferred (later phase).
- Hashing: Argon2id via `argon2-cffi` defaults; `check_needs_rehash` on log-in upgrades old hashes.
- The rules live once, on the server (`identity_access.domain.passwords`). The web form shows the length hint and
  checks length as you type; the server checks everything and returns field errors.

---

## Topic 4 — Sessions and CSRF

### 4.1 Session

- Cookie `__Host-signora_session`: 256-bit token; `HttpOnly; Secure; SameSite=Lax; Path=/`; no `Domain`, no
  `Max-Age` beyond the idle limit. The database stores `sha256(token)`.
- Ends after **12 hours idle** only (owner decision: no absolute limit; recorded as a known trade-off — OWASP also
  recommends an absolute timeout; log-out, password reset/change and removal still end sessions).
- `last_seen_at` is updated at most every **5 minutes**, so the idle timeout is accurate to within 5 minutes.
- New token on every log-in (prevents session fixation). Log-out deletes the row and clears both cookies.
- The workspace comes from the user (one workspace per user), so the session row carries no workspace.
- The housekeeping sweep deletes sessions idle for longer than the limit.

### 4.2 Resolving the caller

`current_actor` (FastAPI dependency) hashes the cookie and runs one query joining `sessions`, `users`, `roles` and
`workspaces`. It returns an `Actor(user_id, workspace_id, email, name, role_key, permissions, is_creator)` or raises
`401 unauthenticated` (no cookie, unknown or idle session, deactivated user). It sets `request.state.actor_id`, which
the idempotency guard uses as the key scope.

### 4.3 CSRF (two layers, OWASP)

1. **Origin check** (kernel middleware, every unsafe method under `/api/`): reject with `403 cross-site-request` when
   `Sec-Fetch-Site` is `cross-site`/`same-site`, or when an `Origin` header is present and differs from
   `PUBLIC_BASE_URL`. Requests with neither header (non-browser clients) pass; browsers always send `Origin` on
   cross-origin POSTs. This also blocks log-in CSRF.
2. **Signed double-submit token** (authenticated unsafe requests): `csrf = HMAC-SHA256(SECRET_KEY, "csrf:" ||
   session_id_hash)`, set in the readable cookie `__Host-signora_csrf` at log-in; the web client sends it in
   `X-CSRF-Token`; the server recomputes and compares in constant time → `403 csrf-failed` otherwise. Nothing is
   stored (the platform design's `csrf_hash` column is dropped).

### 4.4 Schema — `sessions`

| Column | Type | Notes |
|---|---|---|
| `id_hash` | bytea | PK, 32 bytes |
| `user_id` | uuid | FK `users` ON DELETE CASCADE; indexed |
| `created_at`, `last_seen_at` | timestamptz | `last_seen_at` indexed (sweep) |
| `ip` | inet null | at log-in |
| `user_agent` | text null | at log-in, ≤ 512 chars |

---

## Topic 5 — One workspace per user; tenant isolation

- `users.workspace_id` is required and never changes; there is no memberships table, no switcher and no workspace
  creation outside sign-up.
- Removing a member **deactivates** the user (`deactivated_at`): their id stays valid for audit and envelopes. A
  deactivated user with the right password sees `403 access-removed` ("Your access to *Acme Law* was removed"); with
  a wrong password the generic error. Password reset sends them nothing.
- Isolation: repository functions take `workspace_id` as a required argument and every query filters on it; the
  workspace always comes from the session, never from the URL or body. Ids of another workspace answer `404`.
  Postgres row-level security remains a hardening item.

---

## Topic 6 — Invites

### 6.1 Create — `POST /api/v1/invites {email, role_id}` (`members.manage`, `Idempotency-Key`)

| Situation | Response | Effect |
|---|---|---|
| New email | `201` invite | invite saved; invite email sent |
| Active member of this workspace | `409 already-member` | none (the inviter sees the member list anyway) |
| Pending invite for the email | `201` invite | treated as a resend: new token, old link dead, expiry restarts |
| Deactivated member of this workspace | `201` invite | normal invite; accepting restores the user |
| Email of another workspace's user (active or not) | `201` invite | invite shown as pending, never acceptable; the person is emailed that their address already belongs to another workspace |

Limits: **50** invites per workspace per hour; resend **once a minute** per invite. The response never differs
between the first, third and fifth rows.

### 6.2 Accept

1. `PUBLIC_BASE_URL/invite#<token>` → `POST /api/v1/invites/verify {token}` →
   `200 {email, workspace_name, role_name, inviter_name}` or `410 link-expired`. If the browser is signed in as
   someone else, the page logs them out first, with a notice.
2. `POST /api/v1/invites/accept {token, name, password}` (`Idempotency-Key`). One transaction: lock the invite
   (pending, unexpired, not revoked); if the email belongs to another workspace → `409 email-in-other-workspace`
   (safe: only the email's owner holds the link); create the user with the invite's role, or reactivate the
   deactivated member with the new password and role; mark accepted; audit `member.joined` or `member.restored`.
   `201 {"email": ...}`; the page logs in as after sign-up.
3. Two pending invites from two companies for one new email: the first accepted wins.

### 6.3 Manage

`GET /api/v1/invites` (pending), `POST /api/v1/invites/{id}/resend`, `DELETE /api/v1/invites/{id}` — all
`members.manage`. Audit `invite.created`, `invite.resent`, `invite.revoked`.

### 6.4 Schema — `invites`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, `uuidv7()` | PK |
| `workspace_id` | uuid | FK |
| `email` | text | normalised |
| `role_id` | uuid | FK `(role_id, workspace_id)` → `roles(id, workspace_id)`: the role must be this workspace's |
| `token_hash` | bytea | unique |
| `invited_by` | uuid | FK `users` |
| `created_at`, `expires_at` (**7 days**), `accepted_at`, `revoked_at` | timestamptz | |

Partial unique index `(workspace_id, email) WHERE accepted_at IS NULL AND revoked_at IS NULL`: one pending invite
per email per workspace.

---

## Topic 7 — Log-in and throttling

`POST /api/v1/auth/login {email, password}`:

| Situation | Response |
|---|---|
| Throttled (email or IP) | `429 rate-limited` + `Retry-After` (checked before the password, so even a correct password waits) |
| Unknown email | `401 invalid-credentials` after verifying against a dummy Argon2id hash (same timing) |
| Wrong password | `401 invalid-credentials`; failure recorded for the email and the IP |
| Right password, deactivated | `403 access-removed` |
| Right password | `200` with `/me` body; new session; both cookies set; failures for the email reset; hash upgraded if needed |

`POST /auth/logout` deletes the session and clears the cookies (`204`, also when already signed out).

### 7.1 Rate limiter (`signora.kernel.ratelimit`)

```python
class RateLimiter(Protocol):
    def consume(self, key: str, *, limit: int, window: timedelta) -> int | None: ...  # retry-after s, or None
    def peek_backoff(self, key: str) -> int | None: ...                              # retry-after s, or None
    def record_failure(self, key: str, *, free: int, base: timedelta, cap: timedelta) -> None: ...
    def reset(self, key: str) -> None: ...
```

`InMemoryRateLimiter`: thread-safe (one lock), sliding-window counters plus failure streaks, in an LRU-bounded dict
(**100 000** keys). `RATE_LIMITER_BACKEND=memory` today; a Redis implementation is one new class and a setting value.
Keys are namespaced (`login:email:<email>`, `login:ip:<ip>`, `email:signup:<email>`, `invite:ws:<id>`…). One limiter
enforces every limit in this phase.

---

## Topic 8 — Access rules, members, account settings

### 8.1 Permissions in code, roles as data

- Catalogue (code, `identity_access.domain.permissions.Permission`): `members.manage`, `members.directory`,
  `roles.manage`, `workspace.rename`. Later phases add their own (e.g. `projects.create`).
- `roles` table per workspace: `id`, `workspace_id`, `key`, `name`, `permissions text[]`, `is_system`,
  `created_at`; unique `(workspace_id, key)` and `(id, workspace_id)`.
- Defaults created with each workspace:
  - **Read/write** (`read_write`): `members.directory`, `workspace.rename`;
  - **Read** (`read`): none.
- Permission strings not in the catalogue are ignored (logged once), so a role row written by a newer release does
  not break an older one.
- `authorize(actor, permission)` is a set lookup; routes declare `Depends(require(Permission.X))`. Nothing compares
  role names.
- Safety rules stay in code: the creator holds every permission; the creator cannot be demoted or removed; nobody
  removes themselves.
- Changing a company's rules = updating its `roles` rows; no migration, no deploy. A creator-only role editor
  (`roles.manage`) is a later phase.

### 8.2 Endpoints

| Endpoint | Permission |
|---|---|
| `GET /api/v1/me` | signed in |
| `PATCH /api/v1/me {name}` | signed in |
| `POST /api/v1/me/password {current_password, new_password}` | signed in; ends other sessions; *password changed* email |
| `PATCH /api/v1/workspace {name}` | `workspace.rename` |
| `GET /api/v1/members` (with roles, creator flag, join date) | `members.manage` |
| `GET /api/v1/members/directory` (id, name, email) | `members.directory` |
| `GET /api/v1/roles` | `members.manage` |
| `PATCH /api/v1/members/{id} {role_id}` | `members.manage`; not the creator |
| `DELETE /api/v1/members/{id}` | `members.manage`; not the creator, not yourself; ends their sessions |

Role changes take effect on the member's next request (the role is read per request). The guarded update
`UPDATE users SET role_id = … WHERE id = :id AND workspace_id = :ws AND id <> workspaces.created_by` makes the
creator rule hold under concurrency.

### 8.3 Schema — `workspaces`, `users`

`workspaces`: `id`, `name`, `created_by` (FK `users`, null only for the reserved system workspace), `created_at`.
The migration inserts the reserved system workspace (`00000000-…-0000`) used by the system audit chain.

`users`: `id`, `workspace_id` (FK), `role_id` (FK `(role_id, workspace_id)` → `roles`), `email` (normalised, unique),
`name`, `password_hash`, `password_changed_at`, `created_at`, `last_login_at`, `deactivated_at`.

`email_tokens`: `id`, `purpose` (`signup` \| `password_reset`), `email`, `user_id` (null for sign-up),
`token_hash` (unique), `created_at`, `expires_at`, `used_at`. Index `(purpose, email) WHERE used_at IS NULL`.
The sweep deletes rows 7 days after expiry.

Email normalisation (`normalize_email`, one function): trim, lowercase the whole address, reject over 254 characters
or invalid syntax (`email-validator` via pydantic). Dots and `+tags` are kept as typed.

### 8.4 Audit and security log

- Workspace chain (`AuditChain.workspace`): `workspace.created`, `workspace.renamed`, `member.joined`,
  `member.restored`, `member.role_changed` (from, to), `member.removed`, `invite.created`, `invite.resent`,
  `invite.revoked`. Actor = `Actor("user", id, email)`.
- Security log (`signora.security` logger, structured JSON): `auth.login_succeeded`, `auth.login_failed` (email
  domain only), `auth.login_throttled`, `auth.logout`, `auth.password_reset`, `auth.password_changed`.

---

## Architecture

- **Modules** (modular monolith, ADR-008):
  - `signora.modules.notifications` — leaf module (imports only the kernel). Public: `send_email`, `render_layout`,
    `EmailAction`, `RenderedEmail`.
  - `signora.modules.identity_access` — imports the kernel, `audit` and `notifications` public interfaces. Public:
    `Actor`, `Permission`, `current_actor`, `require`, `authorize`, `router`.
  - `signora.kernel.ratelimit` — shared limiter; `signora.kernel.http` gains the Origin check.
- **Dependency direction**: `identity_access → notifications, audit → kernel`. Import-linter contracts protect each
  module's internals and keep `domain` packages free of web and database libraries.
- **Jobs**: `identity.signup_request`, `identity.password_reset_request`, `notifications.send_email`, plus the
  sweeps `sweep.identity` (expired tokens, idle sessions) and `sweep.email_messages`.

### ADR-A1 — Roles as data (supersedes "two access levels only" in the platform design v2)

- *Context*: companies may need different rules (who invites, who renames) without a release.
- *Decision*: permissions are a code catalogue; roles are rows mapping to permissions; lock-out rules stay in code.
- *Consequences*: changing rules is a data change; a new kind of action still needs code. Slightly more schema now
  (one table, one FK) in exchange for no rewrite later.

### ADR-A2 — Email first sign-up with job-side lookups

- *Context*: sign-up and reset must not reveal registered emails, including through timing.
- *Decision*: the request only rate-limits and enqueues; the worker looks up and chooses the email.
- *Consequences*: constant-time responses; sign-up depends on email delivery (Mailpit locally).

### ADR-A3 — In-process email delivery, provider behind a transport interface

- *Decision*: one module, one function, transports `sendgrid` / `smtp` / `mailpit` chosen by configuration; no HTTP
  send endpoint. SendGrid first (owner's existing key), Gmail SMTP as a drop-in.
- *Consequences*: `@gmail.com` senders through SendGrid may land in spam (no domain authentication); switching to
  Gmail SMTP is a `.env` change.

## Algorithms and complexity

| Operation | Approach | Cost |
|---|---|---|
| Session check | SHA-256 of cookie, PK lookup joined to user/role/workspace | O(1) index lookups, one query |
| Permission check | set membership on the actor's permissions | O(1) |
| Common-password check | in-memory `frozenset` of 100 000 lowercased entries | O(1) per check, ~4 MB once |
| Rate limiting | per-key sliding window (deque of timestamps) + streak counter in an LRU `OrderedDict` | O(1) amortised per hit, O(limit) memory per key, bounded keys |
| Token verification | SHA-256 then unique-index lookup | O(1) |
| Password hashing | Argon2id | intentionally ~50–100 ms, 64 MiB |

## Interfaces and error codes

New problem codes: `invalid-credentials` (401), `access-removed` (403), `csrf-failed` (403),
`cross-site-request` (403), `link-expired` (410), `account-exists` (409), `already-member` (409),
`email-in-other-workspace` (409), `creator-protected` (409), `cannot-remove-self` (409). Existing:
`unauthenticated`, `permission-denied`, `not-found`, `validation-failed`, `rate-limited`.

## Frontend (screens 02, 03, 04, 19 + new pages)

- Routes: `/signup`, `/signup/verify`, `/login`, `/forgot-password`, `/reset-password`, `/invite`, `/` (console
  home, placeholder until Phase 3), `/people` (only with `members.manage`), `/settings` (name, password; workspace
  name with `workspace.rename`).
- `features/auth` (sign-up, verify, log-in, forgot, reset, invite), `features/people`, `features/account`;
  `shared/session` (`useSession()` from `GET /me`, sign-out); `shared/ui/PasswordField` (show/hide, password-manager
  friendly `autocomplete`).
- The API client adds `X-CSRF-Token` from the CSRF cookie to unsafe requests; a `401` from `/me` sends the user to
  `/login?next=…`. The Next.js proxy redirects console routes without a session cookie to `/login` (presence only;
  validity is the API's decision).
- Navigation shows People only with `members.manage`.
- **Design-system deviation** (recorded in `docs/design-system/README.md`): screen 02 asks only for the email; the
  verify page carries the prototype's firm name, name and password fields.

## Configuration (new or changed)

`EMAIL_PROVIDER` (`sendgrid` \| `smtp` \| `mailpit`), `SENDGRID_API_KEY`, `MAILPIT_HOST`, `MAILPIT_SMTP_PORT`,
`AUTH_SESSION_IDLE_HOURS=12`, `AUTH_SESSION_TOUCH_MINUTES=5`, `AUTH_SIGNUP_LINK_HOURS=24`,
`AUTH_RESET_LINK_MINUTES=30`, `AUTH_INVITE_DAYS=7`, `AUTH_EMAIL_COOLDOWN_SECONDS=60`,
`AUTH_EMAIL_HOURLY_LIMIT=5`, `AUTH_INVITES_PER_HOUR=50`, `AUTH_LOGIN_FREE_ATTEMPTS=5`,
`AUTH_LOGIN_BACKOFF_CAP_MINUTES=15`, `AUTH_LOGIN_IP_LIMIT=100`, `AUTH_LOGIN_IP_WINDOW_MINUTES=15`,
`AUTH_PASSWORD_MIN_LENGTH=12`, `RATE_LIMITER_BACKEND=memory`, `RATE_LIMITER_MAX_KEYS=100000`.
Production requires the chosen email provider's credentials.

## Test strategy

| Area | Tests |
|---|---|
| Domain | email normalisation; password policy (length after NFKC, common list, 128 cap); token hashing; permission parsing (unknown ignored) |
| Rate limiter | window, cooldown, backoff doubling and cap, reset, LRU bound, thread safety |
| Sign-up | identical 202 for new/existing/throttled; job sends the right email; verify/complete; expired/used link; race (two links) → one user; idempotent replay; audit entries |
| Reset | identical 202; nothing for unknown/deactivated; sessions deleted; token single-use; 30-minute expiry |
| Log-in | generic 401 for unknown/wrong; dummy-hash path taken; backoff and IP limits; deactivated 403; rehash on parameter change; new session per log-in |
| Sessions/CSRF | cookie flags; idle expiry; touch throttled to 5 min; Origin check (cross-site 403, same-origin and no-header pass); CSRF token required and verified |
| Invites | each row of the 6.1 table; resend kills old link; revoke; accept creates/restores; other-workspace race; limits |
| Members | permission matrix per endpoint; creator protections under concurrency; removal ends sessions; directory fields only |
| Isolation | every endpoint with an id: other workspace's id → 404 |
| Email | transport outcomes (sent / transient / permanent) with fake transports; body purge; daily limit; dedupe |
| Web | Vitest for forms (validation, error display, CSRF header, 401 redirect); Playwright-style headless check of the full flow on the live URL |

## Task tracker

| # | Task | Status | Evidence of completion |
|---|------|--------|------------------------|
| 2.1 | Phase 2 LLD (this file), design-system deviation, platform doc updates | done | this file |
| 2.2 | Configuration: auth group, email providers (SendGrid, Mailpit), `.env.example` | done | commit 421959c; config tests: SendGrid needs its key not SMTP, production rejects Mailpit, defaults match this design |
| 2.3 | `kernel/ratelimit`: `RateLimiter` protocol, in-memory implementation | done | commit 61776ec; 10 tests incl. LRU bound and 20 threads never exceeding the limit |
| 2.4 | `kernel/http`: Origin check (CSRF layer 1) | done | commit 6f14361; cross-site and same-site refused, same-origin/none/matching Origin/no header pass, safe methods and non-API paths untouched |
| 2.5 | `notifications`: schema, `send_email`, layout, transports, delivery job, sweep, Mailpit in compose | done | 29 tests: escaping, queued with the caller's transaction (rollback sends nothing), dedupe, sent/permanent/transient/max-attempts/daily-limit outcomes with body purge, SendGrid payload (tracking off) and status mapping, real SMTP delivery to Mailpit, SMTP error mapping, provider selection. Also fixed: the API process now registers job kinds (Phase 1 documented it but only the worker did) |
| 2.6 | `identity_access` domain: emails, passwords, tokens, permissions | done | 24 tests: normalisation keeps dots and +tags, invalid emails, NFKC length (full-width), 128 cap, NCSC common list (99 840 entries, pinned SecLists commit in `domain/data/README.md`), Argon2id with rehash flag, 256-bit tokens, session-bound CSRF, unknown permissions ignored, default roles. Domain kept pure by the import contract |
| 2.7 | `identity_access` schema: workspaces, roles, users, sessions, email tokens, invites; system workspace | todo | — |
| 2.8 | Sessions, `current_actor`, CSRF token, authorisation, log-in/log-out/me, throttling | todo | — |
| 2.9 | Sign-up: request job, verify, complete, emails | todo | — |
| 2.10 | Password reset and password change | todo | — |
| 2.11 | Invites: create/resend/revoke/list, verify/accept | todo | — |
| 2.12 | Members, directory, roles list, role change, removal, workspace rename, profile | todo | — |
| 2.13 | Contracts; web: API client CSRF/401, session, `PasswordField`, auth pages | todo | — |
| 2.14 | Web: console navigation, People, Settings | todo | — |
| 2.15 | Deploy: compose and env, SendGrid wiring, live end-to-end check, test email | todo | — |
