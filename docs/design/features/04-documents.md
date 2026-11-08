# Phase 4 — Documents and versions (LLD)

Parent design: [`../signora-platform.md`](../signora-platform.md) · Previous: [`03-departments.md`](03-departments.md) ·
Branch: `phase-4/documents`

A department holds **documents**, its only entity. A document is an agreement a firm sends for signing ("Engagement
letter", "NDA"). It is uploaded once, kept as immutable **versions**, and later sent many times (Phase 7). This phase
covers documents, uploading, processing to a PDF, versions and viewing. Field detection (Phase 5) and review (Phase 6)
build on it.

Naming (owner decision 2026-11-07): the entity is called **document** everywhere, in the interface and the code. Phase 3
said "files"; its permission names and screen text are renamed in this phase (§1.6).

This document is written topic by topic; a topic is recorded here as soon as it is agreed.

## Topic status

| # | Topic | Status |
|---|---|---|
| 1 | What a document is | **agreed** (2026-11-07) |
| 2 | Uploading | open. Owner input so far: 200-page limit question answered below; password-protected PDFs are unlocked with a password the uploader enters |
| 3 | Processing (DOCX to PDF, page facts, needs-OCR check, failures) | open |
| 4 | Versions. Owner input so far: the latest version is current by default; any version can be made current | open |
| 5 | Viewing. Owner input so far: inline viewing for staff and signers; pdf.js (or similar) for now, a richer viewer later | open |
| 6 | Screens and behaviour (including the dropzones carried from Phase 3) | open |

---

## Topic 1 — What a document is

### 1.1 The document

One agreement inside one department. It has:

- **Name**: what people call it ("Engagement letter").
- **Description**: what the document is, **written by the AI** from the first version (Phase 5 gives the AI the whole
  first page as context), and editable by people.
- **Versions**: each upload is a new, immutable version (topic 4). Each version carries the uploader's
  **instructions for the AI** for that upload (§1.3).
- **Require email code**: on by default (carried from Phase 3 topic 5). Per document, not per version; each send
  copies the value it had when sent (Phase 7), so a later change never affects a send already out.

### 1.2 Rules

- **Name**: 1-120 characters after trimming and collapsing runs of spaces; stored as typed.
- **Unique within the department, ignoring case, among active documents.** Two departments may each have an "NDA".
  An archived document frees its name; restoring onto a taken name answers `409 document-name-taken` (rename first),
  as for departments.
- **Archive and restore only, no delete** (owner decision). An archived document cannot get new versions or be
  sent; sends already out are unaffected. A document in an archived department is read-only.
- **Access** (Phase 3 topic 2): everyone in the company lists and opens documents; creating, renaming, editing the
  description or the email-code setting, uploading and archiving need edit access in that department
  (`documents.send`, §1.6).

### 1.3 Description and instructions for the AI (owner decision)

Two separate things, never mixed:

| | Instructions for the AI | Description |
|---|---|---|
| Written by | the uploader, optionally, with each upload | the AI; people may edit it |
| Belongs to | one version | the document |
| Purpose | input: context or guidance for detection ("two clients sign; the firm countersigns") | output: what the document is, shown on lists and the document page |
| Limit | up to 1,000 characters | up to 500 characters |

- The AI writes the description **once**, from the first version that processes successfully, and only while the
  description is empty. Later versions never rewrite it; they have their own instructions only.
- A person may edit the description at any time. Once a person has written it, the AI never writes it again.
- The screen labels an AI-written description "Written by AI" until a person edits it (`description_source`).
- If the AI cannot write one (failure, needs OCR), the description stays empty and a person may write it.
- The instructions are the uploader's own text, passed to the AI as context inside a clearly delimited block. They
  can steer detection but never bypass validation of the AI's output (Phase 5).

### 1.4 Schema (migration in this phase)

```sql
CREATE TABLE documents (
  id                  uuid PRIMARY KEY DEFAULT uuidv7(),
  workspace_id        uuid NOT NULL,
  department_id       uuid NOT NULL,
  name                text NOT NULL,
  description         text NOT NULL DEFAULT '',
  description_source  text NOT NULL DEFAULT 'none'
                      CHECK (description_source IN ('none', 'ai', 'person')),
  require_email_code  boolean NOT NULL DEFAULT true,
  current_version_id  uuid,                -- topic 4
  created_by          uuid NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  archived_at         timestamptz,
  archived_by         uuid,
  UNIQUE (id, workspace_id),
  FOREIGN KEY (department_id, workspace_id) REFERENCES departments (id, workspace_id),
  FOREIGN KEY (created_by, workspace_id) REFERENCES users (id, workspace_id),
  CHECK (char_length(name) BETWEEN 1 AND 120),
  CHECK (char_length(description) <= 500)
);
CREATE UNIQUE INDEX uq_documents_active_name
  ON documents (department_id, lower(name)) WHERE archived_at IS NULL;
CREATE INDEX ix_documents_department ON documents (department_id, archived_at);
```

`document_versions` (topic 4) gains `ai_instructions text NOT NULL DEFAULT ''` (up to 1,000 characters).

### 1.5 Audit (company chain)

`document.created`, `document.renamed`, `document.description_changed` (with who: AI or person),
`document.email_code_changed`, `document.archived`, `document.restored`. Version events come with topic 4.

### 1.6 Renaming "files" to "documents" (owner decision)

The first task of this phase: permissions `files.view_sends` and `files.send` become `documents.view_sends` and
`documents.send` (a data migration rewrites them in every company's roles; the permission enum, tests and contracts
follow), and screen text says "documents" ("No documents yet."). Phase 3's design doc is left as written, with a
note pointing here.

---

## Task tracker

| # | Task | Status | Evidence of completion |
|---|------|--------|------------------------|
| 4.1 | Phase 4 LLD (this file), topics 1-6 | in progress | topic 1 recorded |
