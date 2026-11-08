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
| 2 | Uploading | **agreed** (2026-11-07) |
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

## Topic 2 — Uploading

### 2.1 Accepted files and limits (owner decisions)

- **PDF and Word (.docx) only**, recognised from the contents, never the file name or the browser's type:
  PDF starts with `%PDF-` within the first 1,024 bytes; .docx is a ZIP holding `[Content_Types].xml` and
  `word/document.xml`. Old .doc, .odt and .rtf are refused (they convert less faithfully; the brief names PDF and DOCX).
- **50 MB** per file and **200 pages** per document (a .docx is counted after conversion, topic 3). Both are settings
  (`DOCUMENT_MAX_BYTES`, `DOCUMENT_MAX_PAGES`), so raising them is an `.env` change. The platform requirement to
  handle documents of 100+ pages is why the page limit is 200, not 100.
- **60 uploads per person per hour** (kernel rate limiter). No storage quota for now.

### 2.2 Two steps: send the bytes, then decide

An upload is split so the bytes travel once, whatever the person decides next (the duplicate question, a list of
several files, a name change):

1. **`POST /api/v1/uploads`** (multipart, one file, `Idempotency-Key`). The API streams the body to a temporary file,
   refusing it the moment it passes 50 MB (the declared length is not trusted), computes SHA-256 while streaming,
   checks the type, and stores the bytes in the blob store under their hash (identical bytes are stored once). It
   answers `201 {upload_id, filename, bytes, sha256, kind: "pdf" | "docx", duplicate}` where `duplicate` is set when
   the same bytes already exist in the target department (§2.3). An upload belongs to the person and the department
   it was sent for and expires after 24 hours if unused (a cleanup job removes the record; the blob is removed only
   if nothing else references it, the hardening rule carried in the platform tracker).
2. **Use it**, once:
   - `POST /api/v1/departments/{id}/documents` `{name, ai_instructions, upload_id, allow_duplicate}` creates a
     document with its first version, or
   - `POST /api/v1/documents/{id}/versions` `{ai_instructions, upload_id}` adds a version (topic 4).

Both need edit access in the department; an upload used once cannot be used again (`409 upload-used`).

### 2.3 The same file twice in a department (owner decision: a hard rule)

The same bytes (same SHA-256) never silently become a second copy or a new version within one department.

- When an upload matches any version of any document in the department (archived documents included, marked as
  such), the screen shows a dialog: **"This file is already in Finance as Engagement letter, version 2. Upload it
  anyway as a separate document?"**
  - **Upload anyway**: it becomes its **own new document**, never a version of the existing one. Its name is the
    file name; if that name is taken in the department, the dialog asks for another name before creating.
  - **Cancel**: nothing is created, and the screen says "Upload cancelled. Nothing was added."
- This applies when creating a document and when adding a version: a file identical to an existing version can only
  ever become a separate document. The add-version request refuses it (`409 duplicate-file`), so the rule holds on
  the server, not only in the dialog.
- The server enforces the question too: creating a document from a duplicate upload without `allow_duplicate: true`
  answers `409 duplicate-file` with the existing document and version.
- Other departments are not checked; the same file may be used independently in each.

### 2.4 Several files at once (owner decision)

Dropping several files makes **one document per file**. Each file is uploaded (step 1) and listed before anything
is created, with its name (from the file name without the extension, editable), its instructions for the AI, and any
problem or duplicate question for that file. "Create N documents" then creates the ones without problems.

### 2.5 Problems shown to the person

| Case | Message (on that file) |
|---|---|
| Not a PDF or .docx | "Upload a PDF or Word (.docx) file" |
| Over 50 MB | "Upload a file of 50 MB or less" |
| Over 200 pages (found during processing, topic 3) | "This document has N pages. Upload one with 200 or fewer" |
| Damaged PDF | "This PDF can't be opened. Save it again and upload it" |
| Password-protected .docx | "Remove the password in Word and upload it again" |
| PDF that needs a password to open | the version waits as **Needs password** (§2.6) |

### 2.6 PDFs that need a password (owner decision)

- PyMuPDF reports whether a PDF needs a password to open (`needs_pass`). Such a version is stored as uploaded and
  waits in **Needs password**. The password field is shown **only** for a version in that state, on the document
  page, to people with edit access in the department.
- `POST /api/v1/documents/{id}/versions/{version_id}/unlock` `{password}`: the password is tried once
  (`authenticate`). Right: an unlocked copy is saved as the working PDF (signing writes on the pages) and processing
  continues (topic 3). Wrong: `422` "Wrong password".
- 5 wrong tries per version per 15 minutes, then `429` with the wait. The password is never stored, logged or
  audited (the audit records only that the version was unlocked, by whom).
- A PDF that opens without a password but carries edit restrictions (an owner password only) is handled
  automatically; nothing is asked.

### 2.7 Out of scope

Virus scanning (a hardening follow-up). Uploaded files are never executed: the bytes are stored, processing reads
them with PyMuPDF and Gotenberg (isolated, topic 3), and viewers render them with scripts disabled (topic 5).

---

## Task tracker

| # | Task | Status | Evidence of completion |
|---|------|--------|------------------------|
| 4.1 | Phase 4 LLD (this file), topics 1-6 | in progress | topics 1-2 recorded |
