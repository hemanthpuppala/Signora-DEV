# Phase 3 — Departments (LLD)

Parent design: [`../signora-platform.md`](../signora-platform.md) · Previous: [`02-accounts.md`](02-accounts.md) ·
Branch: `phase-3/departments`

A department is how a firm groups the agreements it sends: Finance sends engagement letters, HR sends offer
letters, Intake sends client agreements. A department holds **files**, its only entity: any number of them, each
with its own version history. A file is uploaded once and can be **sent** for signing many times; each send carries
its own clients, their names and emails, and the values filled in for them (sends arrive in Phase 7). There is no
separate "template" entity. The platform design called this a "project"; it is renamed **department** everywhere, in the interface
and in the code (owner decision 2026-11-07: plain, universal, and what firms already call these groups).

This document is written topic by topic; a topic is recorded here as soon as it is agreed.

## Topic status

| # | Topic | Status |
|---|---|---|
| 1 | Departments: what they are and who manages them | **agreed** (2026-11-07) |
| 2 | Who can see and do what inside a department | **agreed** (2026-11-07) |
| 3 | Department settings and defaults | **agreed** (2026-11-07) |
| 4 | Countersigners | **agreed** (2026-11-07) |
| 5 | Signer checks | **agreed** (2026-11-07): nothing at department level |
| 6 | Screens and behaviour | **agreed** (2026-11-07) |

---

## Topic 1 — Departments: what they are and who manages them

### 1.1 What a department is

A named group inside one company ("Finance", "Client Intake"). In later phases it holds files (each with its
versions and sends) and owns their defaults (topics 3-5). Topic 1 covers the department itself: name, description, active or
archived, and who creates and manages it.

### 1.2 Rules

- **Name**: 1-80 characters after trimming and collapsing runs of spaces; stored as typed ("Client Intake").
- **Unique within the company, ignoring case, among active departments.** An archived department frees its name.
  Restoring an archived department whose name is now taken answers `409 department-name-taken` (rename first). Two
  companies can both have "Finance".
- **Description**: optional, up to 500 characters.
- **Archive, never delete** (owner decision: no delete option for now). Departments will hold signed files and audit
  history. Archived = read-only and hidden from the default list; it can be restored.
- **States**: `active` → (archive) → `archived` → (restore) → `active`. Changing an archived department answers
  `409 department-archived` ("Restore it to make changes").

### 1.3 Who can do it (permissions in code, holders as data)

| Permission | Allows | Default holders |
|---|---|---|
| `departments.create` | Create departments | Owner, Editor |
| `departments.manage` | Rename, describe, archive, restore | Owner, Editor |

Everyone in the company can list and open departments (what they see inside is topic 2). People without
`departments.create` do not see "New department" at all (owner decision, design-system principle 5). A data migration adds both permissions
to existing Editor roles (only where the role still has its default permissions).

### 1.4 Schema (migration 0007)

```sql
CREATE TABLE departments (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  workspace_id  uuid NOT NULL REFERENCES workspaces(id),
  name          text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
  description   text NOT NULL DEFAULT '' CHECK (char_length(description) <= 500),
  created_by    uuid NOT NULL REFERENCES users(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  archived_at   timestamptz,
  archived_by   uuid REFERENCES users(id),
  CONSTRAINT archived_together CHECK ((archived_at IS NULL) = (archived_by IS NULL)),
  CONSTRAINT uq_departments_id_workspace_id UNIQUE (id, workspace_id)
);
CREATE UNIQUE INDEX uq_departments_active_name
  ON departments (workspace_id, lower(name)) WHERE archived_at IS NULL;
CREATE INDEX ix_departments_workspace_created ON departments (workspace_id, created_at DESC);
```

- `UNIQUE (id, workspace_id)`: later tables (files, sends, countersigners, grants) reference
  `(department_id, workspace_id)`, as users reference roles, so the database guarantees a child row never points at
  another company's department.
- Two creations with one name at the same moment: the partial unique index decides; the loser answers
  `409 department-name-taken`, never a 500.

### 1.5 API (`/api/v1`, plain `def` handlers, every query scoped to the session's company)

| Method and path | Permission | Request | Responses |
|---|---|---|---|
| `GET /departments?status=active\|archived` | signed in | — | `200 [DepartmentSummary]`, sorted by name |
| `POST /departments` | `departments.create`, `Idempotency-Key` | `{name, description?}` | `201 Department`; `409 department-name-taken`; `422` |
| `GET /departments/{id}` | signed in | — | `200 Department`; `404` (also another company's id) |
| `PATCH /departments/{id}` | `departments.manage` | `{name?, description?}` | `200 Department`; `409 department-name-taken`; `409 department-archived` |
| `POST /departments/{id}/archive` | `departments.manage` | — | `200 Department` (repeat-safe) |
| `POST /departments/{id}/restore` | `departments.manage` | — | `200 Department` (repeat-safe); `409 department-name-taken` |

```
Department        { id, name, description, status: "active" | "archived", created_at, updated_at,
                    archived_at, created_by: {id, name} }
DepartmentSummary { id, name, description, status, created_at, counts: {sent, signed, pending} }
                    // counts of sends; zeros until sends exist (Phase 7)
```

- Archive and restore are guarded state changes (`UPDATE … WHERE archived_at IS NULL`), so a repeat or a race
  returns the current state; following the platform rule, state changes take no `Idempotency-Key`.
- No pagination: a company has tens of departments; the list is capped at 500. Pagination can be added later
  without changing the response items.

### 1.6 Module and interface

- New module `signora.modules.departments`: imports only the kernel, the `audit` module and `identity_access`'s
  public interface (`Actor`, `require`, `Permission`). Import contracts protect its internals and keep its `domain`
  free of web and database libraries.
- Public interface for later phases: `get_department(session, workspace_id, department_id) -> DepartmentRef` (404
  otherwise) and `require_active(department)` (`409 department-archived`).
- Audit (company chain): `department.created`, `department.updated` (changed fields with old and new values),
  `department.archived`, `department.restored`.
- Errors: `department-name-taken` (409), `department-archived` (409).

### 1.7 Complexity

Listing: one indexed query per company, O(D) in its departments. Name uniqueness and lookup by id: one index probe,
O(log n). Archive and restore: one guarded `UPDATE`.

### 1.8 Tests

- Names unique within a company ignoring case; an archived name is freed; two companies share a name.
- Two simultaneous creations with one name: one `201`, one `409`, never a `500`.
- Archive and restore repeat safely; restoring onto a taken name is refused; changing an archived department is
  refused.
- Permission matrix (Owner, Editor, Viewer) on every endpoint; another company's id answers `404` everywhere.
- Every change writes its audit entry.
- Web: people without `departments.create` see no "New department" action.

---

## Topic 2 — Who can see and do what inside a department

### 2.1 Decision (option B)

The company role is the baseline in every department. The Owner can additionally give a person **edit access in one
department** ("Editor in Client Intake"); a grant only raises access there, never lowers it. Rejected: company role
only (an intake clerk would have to be an Editor everywhere), and department membership (nobody would see the whole
firm; the platform design says everyone sees every department).

### 2.2 What each level sees and does

| In a department | Read (company Viewer, no grant) | Edit (company Editor or Owner, or a grant here) |
|---|---|---|
| Its files, their versions, counts (sent, signed, pending) | ✓ | ✓ |
| Each send's client details: names, emails, filled-in values, signed copies | ✗ | ✓ |
| Upload, review, approve and send files | ✗ | ✓ |

Client details stay with the people doing the work (owner decision).

### 2.3 Permissions

Department-level permissions join the code catalogue:

| Permission | Allows (in one department) |
|---|---|
| `files.view_sends` | See sends and their client details |
| `files.send` | Upload, review, approve and send files |

The company Editor role holds both in every department (data, as in Phase 2); the Owner holds everything in code. A
grant gives both in its department only. `departments.create`/`departments.manage` (topic 1) stay company-level.

`can(actor, permission, department)` = the company role allows it **or** the actor holds a grant for that
department. The actor's grants are loaded once per request (one indexed query) and checked as a set lookup, O(1).

### 2.4 Schema (migration 0009)

```sql
CREATE TABLE department_grants (
  department_id uuid NOT NULL,
  workspace_id  uuid NOT NULL,
  user_id       uuid NOT NULL,
  granted_by    uuid NOT NULL REFERENCES users(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (department_id, user_id),
  FOREIGN KEY (department_id, workspace_id) REFERENCES departments (id, workspace_id),
  FOREIGN KEY (user_id, workspace_id) REFERENCES users (id, workspace_id)
);
CREATE INDEX ix_department_grants_user ON department_grants (user_id);
```

The composite keys make a grant to another company's person or department impossible (`users` gains
`UNIQUE (id, workspace_id)`). Removing a member deletes their grants in every department, in the removal's own
transaction (the same hook as countersigners, §4.3); the audit log keeps the history. (Changed in the PR review: the
rows were first kept "for history", but a kept row made the list show, and send back, a person who no longer exists,
so every later save was refused.)

### 2.5 API

| Method and path | Permission | Request | Responses |
|---|---|---|---|
| `GET /departments/{id}/grants` | `members.manage` | — | `200 [{user: {id, name, email}, granted_by, created_at}]` |
| `PUT /departments/{id}/grants` | `members.manage` | `{user_ids: [...]}` (the full list) | `200` the new list; `422` for a user not in the company; `409 department-archived` |

The list holds only grants that add something: active people whose role does not already edit everywhere. A grant
kept by someone later promoted (or the creator) is dormant: `GET` leaves it out and `PUT` leaves it in place, so it
applies again if their role goes back, and a list saved as shown never sends an id the server refuses. (Changed in
the PR review: the list first showed every row, so after a promotion every save was refused with "Already has edit
access through their role".)

`PUT` replaces the list in one transaction (idempotent by nature: the same list twice gives the same state), so no
`Idempotency-Key`. Each department in the list and detail responses carries the caller's `access: "edit" | "read"`
so the interface can show or hide actions. (Implementation change: the design first put a grant list on `/me`, but
`/me` belongs to the identity module, which must not depend on departments; the per-department field is also what
the screens need.)

Audit (company chain): `department.access_granted` and `department.access_revoked`, one entry per person changed.

### 2.6 Tests

- Viewer without a grant: sees files and counts, not sends; cannot send. With a grant in Finance: can in Finance,
  cannot in HR.
- Editor and Owner: can in every department; a grant changes nothing for them.
- Only `members.manage` reads or changes grants; a user or department of another company is refused (422/404).
- Replacing the list adds and removes exactly the difference and audits each change; removing a member deletes their
  grants everywhere.
- Two first saves at once both succeed (the department row is locked while a list is replaced).

---

## Topic 3 — Department settings and defaults

Settings decide how sends from a department behave. They take effect once sends exist (reminders and expiry in
Phases 7 and 10), but the department owns them, so they are designed now.

### 3.1 Settings

| Setting | Meaning | Default | Allowed |
|---|---|---|---|
| Remind every | How often a client who has not signed is reminded | **24 hours** | 1 hour – 30 days |
| Max reminders | Reminders before stopping | **5** | 0 – 20 (0 = never) |
| Expires after | When an unsigned send closes | **14 days** | 1 – 365 days |
| Also notify | Extra people emailed when a send is signed, declined or expires | none | up to 5 emails |

The person who sent a file is always notified; "Also notify" adds others (e.g. a department inbox). Defaults come
from `.env` (`DEFAULT_REMINDER_INTERVAL_HOURS`, `DEFAULT_MAX_REMINDERS`, `DEFAULT_EXPIRY_DAYS`).

### 3.2 How defaults flow (option A, owner decision)

A new department is created with the company defaults copied in; from then on its values are simply its values
(what you see is what applies). A send can override them for that one send (Phase 7). Rejected: live inheritance,
where a changed company default silently changes every department that never customised it, and which would need a
company-settings screen.

### 3.3 Schema (columns on `departments`, migration 0008)

```sql
reminder_interval_hours int    NOT NULL CHECK (reminder_interval_hours BETWEEN 1 AND 720),
max_reminders           int    NOT NULL CHECK (max_reminders BETWEEN 0 AND 20),
expiry_days             int    NOT NULL CHECK (expiry_days BETWEEN 1 AND 365),
notify_emails           text[] NOT NULL DEFAULT '{}' CHECK (cardinality(notify_emails) <= 5)
```

Emails are normalised with the shared `normalize_email` (Phase 2), de-duplicated, order kept.

### 3.4 API

- `GET /departments/{id}` adds `settings: {reminder_interval_hours, max_reminders, expiry_days, notify_emails}`.
- `PATCH /departments/{id}` also accepts any of those fields (`departments.manage`: Owner and Editor; a department
  grant does not include it); `409 department-archived` for an archived department.
- `POST /departments` creates with the company defaults; its body may override any of them.
- Validation errors name the field (`notify_emails[2]`: "Enter a valid email address").
- Audit: `department.updated` lists changed settings with old and new values.

### 3.5 Tests

- A new department carries the company defaults; creation overrides apply; changing `.env` later does not change an
  existing department.
- Each range is enforced at both ends (API 422 and database check); 6 notify emails refused; duplicates and case
  merged.
- A grant holder cannot change settings; an Editor can; changes are audited with old and new values.

---

## Topic 4 — Countersigners

### 4.1 Two separate things

- **How many firm signatures a file needs belongs to the file.** The AI extraction finds the firm-side signature
  blocks (e.g. two partners); in review the user adds or removes those signer slots (Phases 5-6). No fixed number.
- **Who may fill them belongs to the department.** A department keeps an ordered list of company people allowed to
  countersign for it. When a file is sent (Phase 7), its firm slots are filled from that list in order as defaults,
  and the sender can change any of them for that send. The list has no size limit (owner decision).

Countersigning itself (emailed link with a one-time code, or the console) is Phase 9.

### 4.2 Rules

- Any active member can be on the list, Viewers included: a countersigner sees and signs only the sends assigned to
  them, so no edit access to the department is needed.
- Owners and Editors manage the list (`departments.manage`), choosing people from the colleague directory.
- **Removed member** (carried from Phase 2): removing a member takes them off every department's list in the same
  transaction; removal is never blocked. A department with an empty list shows "No countersigner. Choose one in
  settings." **Carried to Phase 9:** sends already waiting for a removed person's signature must be reassigned.

### 4.3 Schema (migration 0010)

```sql
CREATE TABLE department_countersigners (
  department_id uuid NOT NULL,
  workspace_id  uuid NOT NULL,              -- the company: lets the keys below check both rows are its own
  user_id       uuid NOT NULL,
  position      int  NOT NULL CHECK (position >= 1),   -- 1 = first default
  added_by      uuid NOT NULL REFERENCES users(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (department_id, user_id),
  UNIQUE (department_id, position),
  FOREIGN KEY (department_id, workspace_id) REFERENCES departments (id, workspace_id),
  FOREIGN KEY (user_id, workspace_id) REFERENCES users (id, workspace_id)
);
```

`workspace_id` is the company's id (the code keeps "workspace"; people read "company"). It exists so the composite
keys guarantee the department and the person belong to the same company.

Member removal (Phase 2 `remove_member`) deletes the person's rows through a hook the departments module registers
with the identity module (a callback list in its public interface), so identity never imports departments.

### 4.4 API

| Method and path | Permission | Request | Responses |
|---|---|---|---|
| `GET /departments/{id}` | signed in | — | adds `countersigners: [{id, name, email}]` in order |
| `PUT /departments/{id}/countersigners` | `departments.manage` | `{user_ids: [...]}` (ordered, any length) | `200` the new list; `422` inactive/unknown person or duplicate; `409 department-archived` |

The list is replaced in one transaction (repeat-safe, no `Idempotency-Key`). Audit: `department.countersigner_added`,
`department.countersigner_removed`, `department.countersigners_reordered`.

### 4.5 Tests

- Order kept and replaced exactly; duplicates, inactive people and other companies' people refused.
- A Viewer can be designated; a grant holder cannot change the list.
- Removing a member removes them from every list in the same transaction; the department then reports no
  countersigner.

---

## Topic 5 — Signer checks

How a client proves who they are before signing. The checks run in Phase 8 (signing).

### 5.1 Decisions (owner, 2026-11-07)

- **Email code**: opening a signing link sends a 6-digit code to the client's email, required before signing.
  **On by default and configurable per file**, not per department. **Carried to the files phases (4-6):** a per-file
  setting "Require email code" (default on), copied onto each send (Phase 7) so a later change never affects a send
  already out. Trade-off recorded: with the code off, possession of the link is enough to sign (a forwarded email
  suffices), as in DocuSign's default.
- **Department access code** (a code shared outside email): **deferred** (future feature). When it returns, each
  send keeps the code it was sent with, so changing the code never locks out a client already told the old one
  (agreed).
- **ID verification (Stripe Identity)**: **deferred** (future feature); nothing is added for it now (no column, no
  switch), per the design-system principle of not showing options that cannot work.

### 5.2 Effect on Phase 3

No signer-check fields, endpoints or screens in departments.

---

## Topic 6 — Screens and behaviour

Built on prototype screens 05, 06, 08 and 09, following the design-system writing and interaction principles.

### 6.1 Home is the departments list (`/`)

- Navigation: **Departments, People, Settings**. Home is the departments page (the greeting placeholder goes).
- Grid of department cards (prototype 05): name, description, footer with Sent / Signed / Pending counts; sorted
  by name; "Active" and "Archived" tabs.
- "New department" for Owners and Editors only; others do not see it (owner decision: hide, never disable).
- Empty: Owners and Editors see "Create your first department, for example Finance or Client Intake." with the
  button; Viewers see "No departments yet."

### 6.2 New department (`/departments/new`)

Name and description only; settings start from the company defaults (topic 3) and countersigners are added in
settings. **Owner decision:** the page also gets a dropzone to add files while creating; it arrives in **Phase 4**
with uploading (a dropzone that cannot upload is not shown). Design-system deviation: prototype 06 asked for every
setting up front. After creating, the new department's page opens.

### 6.3 Department page (`/departments/{id}`)

- Header: name, description, the three counts. "Settings" link for Owners and Editors.
- Files section: "No files yet." until Phase 4 adds uploading and the department-page dropzone. Read access shows
  files and counts only (prototype 08); edit access will also show sends and client details (topic 2).
- Archived: banner "Archived on 7 November. Restore it to make changes."; everything read-only.

### 6.4 Department settings (`/departments/{id}/settings`, Owners and Editors)

Sections, each saving on its own: **About** (name, description) · **Timing** (remind every, max reminders, expires
after) · **Also notify** (an email field with Add, a list with Remove, Save; the add field disappears at 5) · **Countersigners** (ordered: add from the colleague directory, remove,
move up or down; empty shows "No countersigner. Choose one.") · **People with edit access** (the grants, Owner
only) · **Archive department** at the bottom with a confirmation (an archived department shows "Restore").

### 6.4a Owner review changes (2026-11-07)

- Actions a person cannot take are hidden, never disabled (also design-system principle 5).
- Every table of people scrolls inside its panel past `--table-max-height` (480 px) with the header row kept
  visible; panels are named, keyboard-focusable regions.
- "People with edit access" offers only people a grant would help (not the creator, not roles that edit
  everywhere); the server refuses such grants too (`GET /departments/{id}/grants/candidates`).

### 6.5 Unchanged

People gets no per-department column: edit access is managed in each department's settings. Layout uses the Phase 2
building blocks (`Section`, `FieldGrid`, `FieldAction`, `ActionCell`).

---

## Functional requirements

| # | Requirement |
|---|---|
| FR-D1 | Owners and Editors create departments with a name (unique in the company among active ones, ignoring case) and an optional description; settings start from the company defaults. |
| FR-D2 | Owners and Editors rename, describe, change settings, archive and restore; archived departments are read-only and hidden from the default list. |
| FR-D3 | Everyone in the company lists and opens departments, seeing files and counts; client details of sends need edit access in that department. |
| FR-D4 | The Owner grants a person edit access in one department; grants only raise access. |
| FR-D5 | Owners and Editors keep an ordered countersigner list per department (any active member, no size limit); removing a member takes them off every list. |
| FR-D6 | Department settings: remind every (1 h-30 days), max reminders (0-20), expires after (1-365 days), up to 5 extra notify emails. |
| FR-D7 | Every change is audited in the company chain; another company's ids answer 404. |

## Non-functional requirements

| # | Requirement | Threshold |
|---|---|---|
| NFR-D1 | Tenant isolation | Every query scoped by the session's company; composite keys make cross-company rows impossible; one 404 test per endpoint with an id. |
| NFR-D2 | Access check cost | One indexed query per request for the actor's grants; each check O(1). |
| NFR-D3 | Concurrency | Same-name creations: one 201, one 409, never 500; archive/restore and list replacements repeat-safe. |
| NFR-D4 | List latency | `GET /departments` p95 ≤ 100 ms locally for 500 departments. |

## Decisions (ADRs)

- **ADR-D1 — "Projects" renamed "departments"** in the interface and the code: what firms call these groups; one
  name, no translation layer (unlike Phase 2's workspace/company, whose code predated the decision).
- **ADR-D2 — Company role plus per-department grants (topic 2, option B)**: covers "an intake clerk sends only from
  Intake" with one table, without hiding departments from anyone.
- **ADR-D3 — Defaults copied at creation (topic 3, option A)**: what a department shows is what applies.
- **ADR-D4 — Countersigner count from the file, people from the department (topic 4)**.

## Carried to later phases

- Files phases (4-6): per-file "Require email code" (default on); the new-department and department-page dropzones.
- Phase 7: sends copy the department settings and the file's email-code setting; firm slots filled from the
  countersigner list in order.
- Phase 9: reassign sends waiting for a removed countersigner.
- Future: department access code (each send keeps its code); Stripe Identity.

## Task tracker

| # | Task | Status | Evidence of completion |
|---|------|--------|------------------------|
| 3.1 | Phase 3 LLD (this file), topics 1-6 | done | this file |
| 3.2 | Permissions `departments.create`, `departments.manage`, `files.view_sends`, `files.send`; Editor role data migration; `users (id, workspace_id)` key | done | migration 0006 (only Editor roles still on their default permissions are extended); default-role, `/me` and roles tests updated; contract regenerated |
| 3.3 | `departments` module: schema (migration 0007), create, list, get, update, archive, restore, audit | done | 13 tests: normalised names, length checks, unique per company ignoring case among active (archived frees it; other companies independent), two simultaneous creations give 201 and 409, sorted lists by status, update audited with old/new, archived refuses changes, archive/restore repeat-safe and audited once, restore onto a taken name 409, Viewer reads only and Editor manages, another company's id 404 everywhere, creation replays with its key |
| 3.4 | Department settings (validation, defaults copied at creation) | done | migration 0008; 15 tests: company defaults copied at creation, creation overrides, later default changes leave existing departments alone, every range enforced by the API (both ends) and the database, notify emails normalised/merged/capped with indexed field errors, changes audited with old and new, Viewers refused. `DEFAULT_MAX_REMINDERS` now capped at 20 to match |
| 3.5 | Department grants: table, API, `can(actor, permission, department)`, `/me` grants | done | migration 0009; `DepartmentAccess.can/level/require` in the public interface; 6 tests: a grant gives edit in that department only and never `departments.manage`, each department reports the caller's access (Viewer with grant, Editor, Owner), replacing the list adds/removes exactly the difference with one audit entry each and repeats safely, only people managers read or change grants, inactive/unknown/other-company people refused with indexed field errors, archived department 409 and foreign department 404. Deviation: per-department `access` field instead of `/me` grants (see §2.5) |
| 3.6 | Countersigners: table, API, member-removal hook | done | migration 0010; identity gains `on_member_removed` (runs in the removal's transaction; identity never imports departments); 6 tests: order kept and replaced (no size limit, Viewers allowed), audited as added/removed/reordered and nothing on a no-op, duplicates/inactive/foreign/unknown people refused with indexed errors, grant holders refused and Editors allowed, member removal deletes the rows in every department (the test fails without the hook), archived department 409 |
| 3.7 | Contracts; web: departments home, new department, department page, archived banner | done | Navigation Departments/People/Settings; design system gains `CardGrid`/`StatCard`/`AddCard` (prototype .pcard), `HeadRow`, `LinkButton` and `UnavailableAction` (disabled with the reason, linked by aria-describedby). 7 Vitest tests: cards with counts and add card for editors, viewers see the disabled action with its reason and the empty state, a taken name points at the name field, creation opens the new department, archived banner with Restore for managers and no Settings, viewers get neither, missing department. `make check`: 344 backend, 66 frontend, build |
| 3.8 | Web: department settings (about, timing, notify, countersigners, edit access, archive) | done | /departments/{id}/settings with sections saving on their own; people picked from the colleague directory; ordered countersigners with Up/Down/Remove in `ActionCell` columns; edit access shown to the Owner only; archive behind a confirmation (`RowActions`). 5 Vitest tests: edit access owner-only, countersigners added/reordered/saved in order, server range error on the field, archive only after confirming, archived department asks to restore first |
| 3.9 | Deploy and live end-to-end check | done | Deployed; migrations 0006-0010 applied on the live database (every company's default Editor role gained the four permissions; Viewer unchanged). Headless run on https://hemanth.tail50655e.ts.net, all 6 steps passing: new company lands on Departments with the empty state, create (name normalised) opens the department, a taken name refused on the field, settings timing and countersigners saved, a Viewer sees departments read-only with the disabled action and its reason, archive after confirming and restore. Found and fixed: two links named "Settings" on the department page (now "Department settings") |

### PR #4 review fixes

| # | Finding | Fix | Evidence |
|---|---------|-----|----------|
| R1 | Two first saves of edit access at once failed with a duplicate key (500): an empty list has no rows to lock | Lock the department row (`FOR NO KEY UPDATE`) while a list is replaced | two-thread test fails without the lock |
| R2 | The same race for countersigners | The same lock | two-thread test fails without the lock |
| R3 | A removed member kept their grants, so the list showed them and every save was refused | Member-removal hook deletes their grants (§2.4) | test fails without the hook |
| R4 | After a promotion, the person stayed in the list and every save was refused; the list also showed removed people and people a grant does not help | The list and `PUT` cover only grants that add something; a promoted person's grant is dormant, left in place (§2.5) | test: promote, list and save, demote, edit access applies again (fails on the old code) |
