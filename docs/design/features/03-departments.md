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
| 4 | Countersigners | open |
| 5 | Signer checks | open |
| 6 | Screens and behaviour | open |

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

Everyone in the company can list and open departments (what they see inside is topic 2). Viewers see "New
department" disabled with "Only owners and editors can create departments." A data migration adds both permissions
to existing Editor roles (only where the role still has its default permissions).

### 1.4 Schema (migration 0006)

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
- Web: Viewers see "New department" disabled with the reason.

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

### 2.4 Schema (migration 0006, with `departments`)

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
`UNIQUE (id, workspace_id)`). A removed member keeps their grant rows for history but cannot sign in, so the grant
has no effect.

### 2.5 API

| Method and path | Permission | Request | Responses |
|---|---|---|---|
| `GET /departments/{id}/grants` | `members.manage` | — | `200 [{user: {id, name, email}, granted_by, created_at}]` |
| `PUT /departments/{id}/grants` | `members.manage` | `{user_ids: [...]}` (the full list) | `200` the new list; `422` for a user not in the company; `409 department-archived` |

`PUT` replaces the list in one transaction (idempotent by nature: the same list twice gives the same state), so no
`Idempotency-Key`. `/me` gains `department_grants: [department ids]` so the interface can show or hide actions.

Audit (company chain): `department.access_granted` and `department.access_revoked`, one entry per person changed.

### 2.6 Tests

- Viewer without a grant: sees files and counts, not sends; cannot send. With a grant in Finance: can in Finance,
  cannot in HR.
- Editor and Owner: can in every department; a grant changes nothing for them.
- Only `members.manage` reads or changes grants; a user or department of another company is refused (422/404).
- Replacing the list adds and removes exactly the difference and audits each change; a removed member's grant has no
  effect.

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

### 3.3 Schema (columns on `departments`, migration 0006)

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

