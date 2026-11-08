# Phase 3 — Departments (LLD)

Parent design: [`../signora-platform.md`](../signora-platform.md) · Previous: [`02-accounts.md`](02-accounts.md) ·
Branch: `phase-3/departments`

A department is how a firm groups the agreements it sends: Finance sends engagement letters, HR sends offer
letters, Intake sends client agreements. Each department will hold its agreement templates and their default
settings. The platform design called this a "project"; it is renamed **department** everywhere, in the interface
and in the code (owner decision 2026-11-07: plain, universal, and what firms already call these groups).

This document is written topic by topic; a topic is recorded here as soon as it is agreed.

## Topic status

| # | Topic | Status |
|---|---|---|
| 1 | Departments: what they are and who manages them | **agreed** (2026-11-07) |
| 2 | Who can see and do what inside a department | open |
| 3 | Department settings and defaults | open |
| 4 | Countersigners | open |
| 5 | Signer checks | open |
| 6 | Screens and behaviour | open |

---

## Topic 1 — Departments: what they are and who manages them

### 1.1 What a department is

A named group inside one company ("Finance", "Client Intake"). In later phases it holds agreement templates and
agreements and owns their defaults (topics 3-5). Topic 1 covers the department itself: name, description, active or
archived, and who creates and manages it.

### 1.2 Rules

- **Name**: 1-80 characters after trimming and collapsing runs of spaces; stored as typed ("Client Intake").
- **Unique within the company, ignoring case, among active departments.** An archived department frees its name.
  Restoring an archived department whose name is now taken answers `409 department-name-taken` (rename first). Two
  companies can both have "Finance".
- **Description**: optional, up to 500 characters.
- **Archive, never delete** (owner decision: no delete option for now). Departments will hold signed agreements and
  audit history. Archived = read-only and hidden from the default list; it can be restored.
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

- `UNIQUE (id, workspace_id)`: later tables (templates, agreements, countersigners) reference
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
                    // counts are zeros until agreements exist (Phase 7)
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
