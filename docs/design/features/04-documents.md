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
| 3 | Processing (DOCX to PDF, page facts, needs-OCR check, failures) | **agreed** (2026-11-07) |
| 4 | Versions | **agreed** (2026-11-07) |
| 5 | Viewing | **agreed** (2026-11-07) |
| 6 | Screens and behaviour (including the dropzones carried from Phase 3) | open |

---

## Topic 1 — What a document is

### 1.1 The document

One agreement inside one department. It has:

- **Name**: what people call it ("Engagement letter"). It starts as what the uploader typed (by default the file
  name without its extension); the AI may propose a better one from the first version (§1.3).
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

### 1.3 Name, description and instructions for the AI (owner decisions)

Instructions are input; the name and description are what the AI may write. Never mixed:

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

**The AI also names the document** (owner addition), in the same request as the description:

- It is given the current name as context and returns a name; when the current name is already apt it returns the
  same name, and nothing changes.
- It renames **once**, from the first version that processes successfully, and only while the name is still the
  one given at upload (`name_source = 'upload'`). If a person renamed the document before then, the AI's name is
  not used. Later versions never rename.
- The AI's name passes the same checks as a typed one (normalised, 1-120 characters). If it is invalid or already
  taken in the department, the current name is kept.
- The screen shows an AI rename as an updated name: "Renamed by AI · was *scan_final_v2*", until a person renames
  it (`name_source = 'person'`). Recorded as `document.renamed` with the AI as the actor.
- The instructions are the uploader's own text, passed to the AI as context inside a clearly delimited block. They
  can steer detection but never bypass validation of the AI's output (Phase 5).

### 1.4 Schema (migration in this phase)

```sql
CREATE TABLE documents (
  id                  uuid PRIMARY KEY DEFAULT uuidv7(),
  workspace_id        uuid NOT NULL,
  department_id       uuid NOT NULL,
  name                text NOT NULL,
  name_source         text NOT NULL DEFAULT 'upload'
                      CHECK (name_source IN ('upload', 'ai', 'person')),
  name_before_ai      text,                -- shown as "was …" after an AI rename
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

`document.created`, `document.renamed` and `document.description_changed` (each with who: AI or person),
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

## Topic 3 — Processing

### 3.1 One job per version

Using an upload (topic 2) creates the version in **Processing** and enqueues a `document.process` job in the same
transaction; the request returns at once. The worker:

1. **.docx to PDF** through Gotenberg (`POST /forms/libreoffice/convert`), which runs without network access behind
   its gateway (platform P0.6). A conversion taking over 2 minutes is a timeout.
2. **Open** the PDF with PyMuPDF. If it needs a password, the version moves to **Needs password** and the job ends;
   unlocking (§2.6) enqueues the job again. A PDF with only edit restrictions (owner password) is saved without them.
3. **Pages**: more than 200 fails the version ("This document has N pages…"). Records the page count and, per page,
   width, height (PDF points) and rotation, which Phase 6 needs to draw fields in place.
4. **Working copy** (owner decision): a copy without JavaScript, embedded files, and launch or other actions that
   run or open something. Form fields are kept (Phase 5 reads AcroForm widgets). The working copy is what people
   view, what signers see, and what the final signed PDF is built from; the original upload is kept untouched,
   identified by its SHA-256. Both are stored in the blob store by hash.
5. **Text check** (§3.2).
6. **Processed**: the version is done and the job publishes `document.version_processed` (kernel events). Phase 5
   subscribes to it to detect fields and to write the name and description (topic 1).

### 3.2 Pages without text: blocked until OCR (owner decision)

- A page **lacks text** when it shows content (images or drawings) but has fewer than 20 characters of extractable
  text: a scanned page, including a scan with a typed page number. A page with no content at all (a blank page) is
  not counted; there is nothing to read on it.
- **If any page lacks text, the version is blocked as Needs OCR.** Nothing is detected or sent from it until OCR
  exists (a later phase). The version records which pages lack text (`pages_without_text`), so the OCR phase can
  handle every case: all pages scanned, some scanned among text pages, a scanned signature page.
- The person sees: "Page 4 is a scanned image. Scanned pages can't be read yet." (or "Pages 1-12 are scanned
  images…"), and may upload a text-based PDF as a new version.

### 3.3 Statuses

| Status | Meaning | Next |
|---|---|---|
| Processing | the job is running or waiting to retry | Processed, Needs password, Needs OCR, Failed |
| Needs password | the PDF needs a password to open (§2.6) | Processing (after unlock) |
| Needs OCR | at least one page lacks text (§3.2) | final in this phase |
| Failed | a permanent problem, or a temporary one after the last retry | Processing (after "Try again", temporary only) |
| Processed | ready for field detection | Phase 5 and 6 add their statuses after this |

### 3.4 Failures

- **Temporary** (Gotenberg unavailable, timeout, blob store error): retried with the job backoff (backbone LLD
  §1.4: 30 s doubling to 1 hour, 8 attempts). After the last attempt the version is **Failed** with
  `failure_temporary = true`.
- **"Try again"** (owner decision): shown only on such a version, to people with edit access.
  `POST /api/v1/documents/{id}/versions/{version_id}/retry` moves it back to Processing and enqueues the job
  (repeat-safe: a version already processing is left alone).
- **Permanent** (damaged PDF, over 200 pages, a .docx Gotenberg cannot convert): **Failed** at once with the
  message from §2.5; no retry, the fix is a new upload.
- The job is idempotent: running it again for a version that is already past Processing does nothing.

### 3.5 Targets and tests

- A 200-page text PDF is processed in under 30 s; a .docx converts in under 60 s (Gotenberg's own time).
- Tests use generated files: a 200-page PDF, a 201-page PDF, a .docx, a password-protected PDF, an
  owner-password-only PDF, a PDF with JavaScript and an embedded file (both gone from the working copy, form fields
  kept), a damaged PDF, a scanned page among text pages, a blank page (not counted), and Gotenberg unavailable
  (retries, then Failed with "Try again").

---

## Topic 4 — Versions

### 4.1 Numbering

Versions of a document are numbered 1, 2, 3… in upload order. The number is assigned under the document row's lock
(as in Phase 3's list fix), so two uploads at once never share or skip a number: `UNIQUE (document_id, version_no)`.

### 4.2 Current version (owner decisions)

The current version is the one new sends use.

- **Only a ready version can be current.** Ready means the AI processing is done: from Phase 5, field detection
  and the name and description have finished; in this phase, before AI exists, it means **Processed**. A version
  that is processing, failed, or needs a password or OCR can never be current. (Sending additionally needs the
  version approved, Phase 6.)
- **The latest becomes current automatically when it is ready.** When a version becomes ready it is made current
  unless a higher-numbered version is already current, so a slow version 3 finishing after version 4 never takes
  over. This applies to version 1 too: a document has no current version until its first version is ready, and the
  document page shows that version's status instead.
- **Any ready version can be made current by hand**, after a confirmation: "Make version 2 current? New sends will
  use it." `POST /api/v1/documents/{id}/current-version` `{version_id}` (edit access; `409 version-not-ready`
  otherwise; repeat-safe).
- A later upload that becomes ready takes over again, even after a person chose an older version.
- Sends keep the version they were sent with (Phase 7); changing the current version only affects new sends.

### 4.3 Immutability

A version's original file, working copy, hashes and page facts never change once recorded. A database trigger
refuses updates to those columns once the version leaves Processing, and refuses deleting versions, so the rule holds
even outside the application code (platform §9). Status, failure details and the AI description may still change.

### 4.4 Schema

```sql
CREATE TABLE document_versions (
  id                  uuid PRIMARY KEY DEFAULT uuidv7(),
  workspace_id        uuid NOT NULL,
  document_id         uuid NOT NULL,
  version_no          integer NOT NULL CHECK (version_no >= 1),
  status              text NOT NULL DEFAULT 'processing'
                      CHECK (status IN ('processing', 'needs_password', 'needs_ocr', 'failed', 'processed')),
  failure_code        text,               -- e.g. too_many_pages, damaged, conversion_failed, unavailable
  failure_temporary   boolean NOT NULL DEFAULT false,
  source_sha256       text NOT NULL,      -- the upload as received
  source_kind         text NOT NULL CHECK (source_kind IN ('pdf', 'docx')),
  source_filename     text NOT NULL,
  source_bytes        bigint NOT NULL,
  pdf_sha256          text,               -- the working copy (§3.1), set when processed
  page_count          integer,
  pages               jsonb,              -- [{width, height, rotation}] in PDF points
  pages_without_text  integer[] NOT NULL DEFAULT '{}',
  ai_instructions     text NOT NULL DEFAULT '' CHECK (char_length(ai_instructions) <= 1000),
  ai_description      text,               -- Phase 5
  uploaded_by         uuid NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  processed_at        timestamptz,
  UNIQUE (id, workspace_id),
  UNIQUE (document_id, version_no),
  FOREIGN KEY (document_id, workspace_id) REFERENCES documents (id, workspace_id),
  FOREIGN KEY (uploaded_by, workspace_id) REFERENCES users (id, workspace_id)
);
CREATE INDEX ix_document_versions_source ON document_versions (workspace_id, source_sha256);  -- duplicate check
```

`documents.current_version_id` references `document_versions (id, workspace_id)` with the document's company.

### 4.5 Audit (company chain)

`document.version_added` (number, file name, hash), `document.version_unlocked`, `document.version_failed`
(reason), `document.version_retried`, `document.current_version_changed` (old and new, and whether automatic).

---

## Topic 5 — Viewing

### 5.1 One viewer, modelled on ScoutBoard's résumé builder (owner decision)

The owner's reference is ScoutBoard's résumé builder (`ScoutBoard/packages/ui/src/primitives/pdf-canvas`): the PDF is
painted on canvases with `pdfjs-dist`, and a **per-page overlay slot** places clickable elements exactly over the
painted page at any zoom. Signora's viewer follows that design, written for this codebase:

- **`PdfViewer`** in the design system (`apps/web/src/shared/ui`), one component for every surface: staff viewing
  now, the field review canvas (Phase 6: field boxes drawn, moved and resized in the overlay), and the signer's page
  (Phase 8: click a signature field to sign, inline for signers). Read-only in this phase.
- **Rendering**: each page on its own canvas at `cssScale × devicePixelRatio`, so it is sharp on high-density screens;
  a new zoom shows the existing bitmap scaled at once and re-renders sharp when the gesture stops; rendering to an
  off-screen canvas first, so pages never blank.
- **Overlay slot**: `renderOverlay({page, scale})` renders inside a box sized to the painted page. Positions are in
  PDF points (as stored in `pages`, topic 4) multiplied by the live scale, so overlays never drift on zoom.
- **Controls**: fit to width (default; suits phones), zoom in and out (buttons, Ctrl or ⌘ with the wheel, trackpad
  pinch), page *n* of *N* with previous and next. Esc clears a selection (used from Phase 6).
- **Large documents** (Signora addition): pages are laid out at their final size at once, but rendered only when near
  the viewport (the visible page first), and pdf.js loads the file by byte ranges, so a 200-page, 50 MB document
  opens quickly. ScoutBoard renders every page; with up to 200 pages Signora must not.
- **Safety**: PDF scripting is never enabled and `isEvalSupported` is off (on top of the working copy having no
  scripts, topic 3). The pdf.js worker is served from Signora's own origin (CSP `worker-src 'self'`). pdf.js is
  lazy-loaded, so it stays out of pages that show no PDF.
- **Not ready**: a version that is not Processed shows its status instead of the viewer. Any ready version can be
  opened from the version history.
- The `pdfjs-dist` version is chosen at implementation from its current release notes (ScoutBoard pins 5.4.296).

### 5.2 Serving

- `GET /api/v1/documents/{id}/versions/{version_id}/pdf`: the **working copy** only, for anyone who can see the
  document. `Content-Type: application/pdf`, `Content-Disposition: inline`, `Cache-Control: private, no-store`,
  `X-Content-Type-Options: nosniff`, and HTTP range requests (`206`) for pdf.js's partial loading.
- `GET /api/v1/documents/{id}/versions/{version_id}/original`: the file exactly as uploaded (the .docx, or the PDF
  before cleaning), always `Content-Disposition: attachment`, never shown in the page, because it may still hold
  scripts. **Anyone who can see the document may download it** (owner decision: Viewers can already view it).
- Signers get their own endpoint in Phase 8, tied to their signing session and their send's version.

### 5.3 Later (owner decision: the richer viewer is this one, extended)

Text search and page thumbnails are not in this phase; they extend the same `PdfViewer` later.

---

## Task tracker

| # | Task | Status | Evidence of completion |
|---|------|--------|------------------------|
| 4.1 | Phase 4 LLD (this file), topics 1-6 | in progress | topics 1-5 recorded |
