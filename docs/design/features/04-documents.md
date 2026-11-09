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
| 6 | Screens and behaviour (including the dropzones carried from Phase 3) | **agreed** (2026-11-07) |

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
  copies the value it had when sent (Phase 7), so a later change never affects a send already out. **Superseded
  (owner decision, 2026-11-09): per envelope only, on the send form (Phase 7); the document page no longer shows it
  and the column and its PATCH field are removed with Phase 7.**

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
- The screen shows the description like any other, with no AI label (owner decision). `description_source` is kept
  only to apply the rule above.
- If the AI cannot write one (failure, needs OCR), the description stays empty and a person may write it.

**The AI also names the document** (owner addition), in the same request as the description:

- It is given the current name as context and returns a name; when the current name is already apt it returns the
  same name, and nothing changes.
- It renames **once**, from the first version that processes successfully, and only while the name is still the
  one given at upload (`name_source = 'upload'`). If a person renamed the document before then, the AI's name is
  not used. Later versions never rename.
- The AI's name passes the same checks as a typed one (normalised, 1-120 characters). If it is invalid or already
  taken in the department, the current name is kept.
- The screen shows the new name like any other, with no AI label (owner decision). A person renaming sets
  `name_source = 'person'`. The audit log records the AI rename as `document.renamed` with the old name and the AI
  as the actor.
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
  The container signatures (ZIP, OLE compound file), which sit at the very start, are checked before the PDF header,
  so a Word file holding an attached PDF is still a Word file (review fix, 4.14).
- **50 MB** per file and **200 pages** per document (a .docx is counted after conversion, topic 3). Both are settings
  (`DOCUMENT_MAX_BYTES`, `DOCUMENT_MAX_PAGES`), so raising them is an `.env` change. The platform requirement to
  handle documents of 100+ pages is why the page limit is 200, not 100.
- **60 uploads per person per hour** (kernel rate limiter). No storage quota for now.

### 2.2 Two steps: send the bytes, then decide

An upload is split so the bytes travel once, whatever the person decides next (the duplicate question, the name and
instructions typed while the bytes are still travelling):

1. **`POST /api/v1/departments/{id}/uploads?filename=…`**, the raw file as the body
   (`application/octet-stream`). The API streams the body to a temporary file, refusing it the moment it passes
   50 MB (a larger declared length is refused before reading), checks the type, and stores the bytes in the blob
   store under their SHA-256 (identical bytes are stored once). It answers `201 {id, filename, kind: "pdf" |
   "docx", bytes, suggested_name, expires_at, duplicate}`, where `duplicate` is set when the same bytes already
   exist in the department (§2.3). An upload belongs to the person and the department it was sent for and is
   forgotten after 24 hours (hourly sweep), used or not; its blob stays (a version may share the bytes; blob
   clean-up is the hardening phase's locked pass, platform tracker P11).
   *Implementation change:* a raw body instead of multipart, because multipart parsers spool the whole file before
   any limit applies, while a raw body is counted as it arrives. No `Idempotency-Key`: a retried upload stores the
   same bytes under the same hash and only leaves an unused upload row, which the sweep removes.
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

### 2.4 One file per upload, many uploads at once (owner decision)

- **Each upload is one file**, making one document (or one version). A dropzone takes one file; dropping several at
  once says "Drop one file at a time".
- **Uploads do not wait for each other.** The bytes start travelling the moment a file is chosen (step 1), while the
  person types its name (prefilled from the file name without the extension) and instructions for the AI; "Add
  document" then creates it. Meanwhile the person may drop the next file. Each upload has its own row with its
  progress, status and any problem or duplicate question.
- **Processing runs in parallel** (topic 3): each version is its own job, and the worker runs up to
  `WORKER_CONCURRENCY` jobs at once (default 8), so ten uploads are processed side by side, not one after another.

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
  (`authenticate`). Right: an unlocked copy is stored (`unlocked_sha256`) and processing continues from it (topic 3);
  the working copy is made from it, unencrypted, because signing writes on the pages. Wrong: `422` "Wrong password".
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
transaction; the request returns at once. **Versions are processed in parallel** (owner question): each is its own
job, and the worker runs up to `WORKER_CONCURRENCY` jobs at once (default 8), so uploads never queue behind one
another unless more than that are running. Word conversions also share Gotenberg, which (8.x documentation,
configuration page) runs one LibreOffice conversion at a time "due to a lock mechanism" and queues the rest; our
`--api-timeout=120s` includes that wait, so under a burst a conversion may time out and is then retried like any
passing failure. PDFs never touch Gotenberg. The worker, for each version:

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

- A page **lacks text** when an image covers at least a third of it and it has fewer than 20 characters of
  extractable text: a scanned page, including a scan with a typed page number. A blank page is not counted, and
  neither is a page with only a little text and lines (a signature block), so neither blocks a document by mistake.
  (Refined at implementation from "images or drawings": a signature line is a drawing.)
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
  §1.4: 30 s doubling to 1 hour, 8 attempts). When the job dies, the version is **Failed** with
  `failure_temporary = true`. The job's `on_dead` hook (`processing.give_up`) does this in the transaction that
  marks the job dead, so it also covers a failure while saving the result and a worker that dies on the last
  attempt (lease expiry), which would otherwise leave the version Processing forever (review fix, 4.12).
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
  only if no higher-numbered version is ready, so a slow version 3 finishing after version 4 never takes over, and
  an older version that becomes ready late (after Try again) never overrides a version a person chose by hand
  (review fix, 4.13: the first rule compared only with the current version, so retrying version 2 overrode a
  person's choice of version 1 while version 3 was ready). This applies to version 1 too: a document has no current version until its first version is ready, and the
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
- **Safety**: PDF scripting never runs: it needs pdf.js's separate sandbox build, which Signora never loads (and
  the working copy has no scripts, topic 3). pdf.js 6 no longer has `isEvalSupported`; it evaluates nothing. The
  worker and its data (fonts, character maps, colour profiles, image decoders) are copied from `pdfjs-dist` into
  `public/pdfjs/<version>/` before dev and build and served from Signora's own origin (CSP `worker-src 'self'`; the
  page policy is not applied to those static files). pdf.js is loaded on first use, never with the page bundle.
- **Not ready**: a version that is not Processed shows its status instead of the viewer. Any ready version can be
  opened from the version history.
- **Layout before loading**: page sizes come from the API's page facts, so all pages are laid out at once and
  scrolling is stable while pdf.js fetches the file by ranges.
- `pdfjs-dist` **6.4.299** (2026-10-03): the newest release older than two weeks; 6.5.438 (2026-11-01) is too fresh
  to adopt, the same rule the platform applies to Gotenberg. ScoutBoard pins 5.4.296.
- Esc to clear a selection arrives with selections, in Phase 6.

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

## Topic 6 — Screens and behaviour

Built from the design system and the writing principles (`docs/design-system/README.md`): actions a person cannot
take are hidden. The owner asked for the ease and conventions of established e-signature products such as
DocuSign: the document is the largest thing on its page, there is one primary action per screen, statuses are plain
words, and consequential actions (make current, archive) ask first.

### 6.1 Department page: documents (prototype 10)

- A table: document (name, with "PDF · 7 pages" under it), current version ("v2"), status. Roles and detection
  columns arrive with Phases 5-6. Rows open the document page.
- Edit access: an **Upload document** button and a dropzone. With no documents, the empty state is the dropzone.
  Dropping a file there opens the upload page with that file already uploading (owner decision).
- Viewers: the table only.

### 6.2 Upload page `/departments/{id}/upload` (prototype 11)

- **One document at a time** (owner decision, revised in Phase 5): the head reads "‹ Documents" (back to the
  department) over **Upload a document**. A dropzone, "Drop a PDF or Word file · up to 50 MB · up to 200 pages",
  until a file is chosen; then that file takes the dropzone's place.
- The file's card: a progress bar while the bytes travel, the **name** (prefilled, editable), **Instructions for
  the AI** (optional) and **Add document**. Problems and the duplicate dialog (§2.3) appear on it. **Remove** brings
  the dropzone back.
- After "Add document" the person is taken to the new document's page, which shows the version's steps (Upload,
  Process, Find fields, Ready) above the viewer until it is ready or needs something (Phase 5).
- A file still uploading has **Cancel**, which stops the transfer; leaving the page stops it too. Nothing is sent
  from a department that is archived or that the person cannot edit: the page explains that instead (review fix,
  4.19).
- *Implementation details:* the duplicate question (§2.3) is asked as soon as that file's upload finishes, so
  nobody types a name for a file they will cancel. When "Upload anyway" meets a taken name, the row's name field
  says so and the person renames it there. Statuses read Processing, Needs password, Scanned pages, Failed and
  Ready. Files are handed from one page to the next in memory (a reload forgets them). A file over the size limit
  is refused before it is sent; the limits come from `/api/v1/meta`, never hard-coded. Routes compose the
  departments and documents features (a feature never imports another).

### 6.3 New department page (carried from Phase 3, owner decision)

- The same dropzone on `/departments/new`, for one file (owner decision, revised in Phase 5): once dropped, the
  file takes the dropzone's place, with **Remove**, and is held in the browser (it cannot be uploaded before the
  department exists).
- On **Create department**, the department is created and the page moves to its upload page, where the held file
  uploads and shows its status until it is done.

### 6.3a The way back (Phase 5, owner decision)

A page below another has no Back button: its head's eyebrow is the way back, "‹ Documents", one shared
`BackLink` (`HeadRow`'s `back`). The department page leads to Departments, a new department to Departments,
department settings to the department, the upload and document pages to the department's documents. The pages in
the navigation (Departments, People, Settings) have none.

### 6.4 Document page `/departments/{id}/documents/{documentId}`

- **Header**: "‹ Documents" (§6.3a) with New version, Edit and Archive document at its end for people with edit
  access; the name with the version shown beside it (V2, a star when current); the description (no AI labels,
  owner decision). Revised in Phase 5: a new version uploads as soon as it is picked from the file picker; once
  the file has arrived, a short form above the viewer takes the optional **instructions for the AI** for that
  version (as the first upload does, §1.3) and **Add version**; then its steps show there until ready.
- **Main area (left, large)**: the viewer (topic 5) on the current version. When the newest version is not ready,
  its state is shown above the viewer of the current one (or alone, for a first version):
  - Processing: "Processing version 3…";
  - Needs password: the password field, only in this state (§2.6);
  - Failed: the message, and **Try again** for temporary failures (§3.4);
  - Needs OCR: which pages are scanned images (§3.2).
- **Side panel (right; below the viewer on phones)**:
  - **Require email code** switch (edit access);
  - **Versions**: number, file name, pages, uploaded by and when, status, a *Current* badge; Open, Download
    original, and **Make current** for ready versions, with the confirmation from §4.2;
  - (the new version is added from the header, see above);
  - **Archive document**, behind a confirmation (edit access); an archived document shows a banner with Restore.
- **Viewers**: the viewer, the versions list, Open and Download original.

### 6.5 Live status: polling while something is processing (owner question: push or poll?)

Considered: Server-Sent Events (one long HTTP response the server writes to), long polling (a request the server
holds until something changes), and short polling.

- Push needs a path from the worker (a separate process) to the API, such as Postgres `LISTEN/NOTIFY`, an
  async streaming endpoint (handlers here are sync, so each held request would occupy a thread), proxy settings so
  Caddy and the Funnel do not buffer it, and reconnect handling. That is a lot of moving parts for a status that
  changes a few times in under a minute.
- **Decision: short polling, only while something is processing.** A page asks for its versions' statuses every
  1 s for the first 10 s, then every 2 s, then every 5 s after a minute, and stops as soon as nothing is processing.
  TanStack Query pauses it in background tabs. Each poll is one small indexed query. Updates appear within about
  2 s, without a reload.
- The polling lives in one hook, so it can be swapped for Server-Sent Events later (Phase 7 dashboards with many
  sends may justify it) without touching the screens.

---

## Functional requirements

| # | Requirement |
|---|---|
| FR-DOC1 | People with edit access in a department create documents by uploading one PDF or .docx file; the name is unique per department among active documents. |
| FR-DOC2 | Each upload is one file; uploads may overlap, and their processing runs in parallel. |
| FR-DOC3 | The file type comes from the contents; files over 50 MB or 200 pages, damaged PDFs and password-protected .docx files are refused with a message. |
| FR-DOC4 | The same file twice in a department never becomes a version; the person may add it as a separate document or cancel. |
| FR-DOC5 | A PDF that needs a password waits until someone with edit access enters it; the password is never stored. |
| FR-DOC6 | Each version is converted (from .docx), measured, cleaned into a working copy and checked for text; any page without text blocks it as Needs OCR. |
| FR-DOC7 | Temporary processing failures retry automatically, then offer Try again; permanent ones fail with a message. |
| FR-DOC8 | Only ready versions are current; the latest ready version becomes current automatically; any ready version can be made current after a confirmation. |
| FR-DOC9 | Versions never change once stored, enforced by the database. |
| FR-DOC10 | Everyone in the company views documents in the shared viewer and downloads originals; documents are archived and restored, never deleted. |
| FR-DOC11 | Statuses update on screen without a reload while something is processing. |

## Non-functional requirements

| # | Requirement | Threshold |
|---|---|---|
| NFR-DOC1 | Upload memory | streamed to disk; API memory does not grow with file size (checked with a 50 MB upload) |
| NFR-DOC2 | Processing time | 200-page text PDF under 30 s; .docx conversion under 60 s |
| NFR-DOC3 | Viewer | first page visible within 2 s for a 200-page, 50 MB PDF on the live URL (range loading, lazy pages) |
| NFR-DOC4 | Isolation | every document, version, upload and blob read is scoped to the caller's company; another company's ids answer 404 |
| NFR-DOC5 | Safety | the working copy has no scripts, embedded files or launch actions; PDF scripting never runs in the viewer; originals only as downloads |

## Decisions (ADRs)

- **ADR-DOC1 — Two-step uploads (topic 2).** Bytes are sent once to `/uploads`, then used to create a document or a
  version, so the duplicate question and editing while uploading never resend 50 MB. Consequence: an `uploads`
  table and a cleanup job for unused uploads.
- **ADR-DOC2 — Working copy beside the original (topic 3).** Viewing, signing and the final PDF use a cleaned working
  copy; the original is kept byte for byte for integrity and download. Consequence: two blobs per version.
- **ADR-DOC3 — Polling, not push, for live status (topic 6).** Push would need `LISTEN/NOTIFY`, async streaming and
  proxy changes for a status that settles in under a minute. Consequence: one hook to replace if push is needed.
- **ADR-DOC4 — One shared PDF viewer modelled on ScoutBoard (topic 5)**, with lazy page rendering for 200 pages,
  reused by review (Phase 6) and signing (Phase 8).

## Carried to later phases

- Phase 5: on `document.version_processed`, detect fields and write the name and description once (topic 1); "ready"
  then means AI processing done (topic 4).
- Phase 6: field boxes in the viewer's overlay; approval before sending.
- Phase 7: sends pin a version and copy "Require email code".
- Phase 8: the signer's PDF endpoint and click-to-sign in the same viewer.
- Later: OCR for versions marked Needs OCR (all page mixes, `pages_without_text`); text search and thumbnails in the
  viewer; virus scanning (hardening).

## Task tracker

| # | Task | Status | Evidence of completion |
|---|------|--------|------------------------|
| 4.1 | Phase 4 LLD (this file), topics 1-6 | done | topics 1-6 agreed and recorded |
| 4.2 | Rename `files.*` permissions to `documents.*` (data migration), screen text | done | migration 0012 renames them in every role (customised ones too) and rewords the Viewer description where still default; test on a throwaway database upgrades and downgrades; enum, tests, contracts and "No documents yet." updated |
| 4.3 | Uploads: streaming to the blob store, type check, size limit, rate limit, `uploads` table, cleanup job | done | migration 0013; kernel `spool_body` (3 tests: within the limit, chunked body stopped at the limit with no file left, declared length refused); 15 upload tests: PDF stored by hash and recorded, .docx recognised whatever its name, PNG/text/ZIP/.docm/.doc/empty refused, password-protected Word asks to remove the password, over the limit 413, base file name kept, Viewer 403, archived 409, unknown and other company 404, 60-per-hour limit, sweep after a day. Raw body instead of multipart (§2.2) |
| 4.4 | Documents and versions: schema, create with an upload, add a version, numbering, duplicate rule, rename, description, email code, archive and restore, audit | done | migration 0014 (the current version references `(id, document_id)`, so it is always this document's); 9 tests: an upload becomes a document with version 1 processing and no current version, audited; an upload is used once, by its uploader, in its department, before it expires; names unique per department ignoring case; the same bytes flagged on upload, refused without confirmation, never a version, allowed as a separate document, other departments unaffected; versions numbered in order (under the document lock); rename/description/email code by a person (sources set to person) and audited; archived refuses versions, restore onto a taken name 409; Viewers read only, other companies 404; creation replays with its key |
| 4.5 | Processing job: Gotenberg conversion, PyMuPDF checks, working copy, text check, statuses, retries, Try again, unlock | done | `pdf.py` (7 tests, no database: page facts as displayed, 200 pages prepared in about a second and 201 refused, damaged PDF, password needed and opened only with it, edit restrictions removed silently, working copy without JavaScript, embedded file or launch link but with its form field, scanned pages found while blank pages and signature blocks are not); `document.process` job (10 tests against Postgres and Gotenberg: queued on create and on a new version, PDF processed and repeat-safe, .docx converted, scanned pages block with "Pages 2-4 and 7…", 201 pages fail with the count and cannot be retried, an outage retries then fails with Try again which processes it, password unlock (wrong 422, right continues, password absent from the audit), five wrong passwords then 429, unlock refused when not locked) |
| 4.6 | Current version rules, make current, immutability trigger | done | migration 0015 (trigger refuses changing a version's source, its processed facts or its unlocked copy, and deleting versions); `current.py` decides under the document lock; 5 tests: the first ready version becomes current (audited as automatic), the latest takes over when ready and a slower older one never does, a version needing OCR never becomes current and cannot be made current (409), any ready version can be made current (repeat-safe; Viewers 403) until a newer one is ready, the database refuses changes and deletes while the AI description may still change |
| 4.7 | Serving: working copy inline with ranges, original as download | done | `BlobStore.path` for serving local files; 5 tests: the working copy inline (`private, no-store`, `nosniff`, `Accept-Ranges`), a byte range answered 206 with its `Content-Range`, the cleaned copy rather than the upload; a version not processed yet answers 409; the original is the exact upload as an attachment with its type; Viewers download, other companies 404 |
| 4.8 | Web: shared `PdfViewer` (pdf.js, overlay slot, zoom, lazy pages) | done | `shared/ui/pdf`: pure layout maths (5 tests: fit, zoom steps, wheel factor, sharp canvas sizes, page in view) and the component (4 tests with pdf.js mocked: every page laid out from the page facts and the file loaded by ranges with assets from our origin, zoom buttons and fit width, the overlay on every page at the live scale, a message when the file cannot be shown); asset copy script; CSP `worker-src 'self'`; checked in a real browser in task 4.11 |
| 4.9 | Web: documents on the department page, upload page, new-department dropzone, polling hook | done | design system gains `Dropzone` (one file; several say "Drop one file at a time"), `Dialog` (native `<dialog>`) and `PageForm` with a `--page-gap` token; `/meta` publishes the upload limits; 12 Vitest tests: polling intervals, the list with versions and plain statuses and no dropzone for read access, a dropped file opens the upload page, upload then name from the file then add with instructions and an idempotency key then live status, handed-over files upload at once, two uploads at the same time, the duplicate question cancelled (nothing added) or confirmed (`allow_duplicate`), a taken name on the field, the server's reason for a refused file, a file over the limit never sent, an archived department explains; 3 department tests updated for the documents slot and the new-department dropzone (files held until the department exists) |
| 4.10 | Web: document page (viewer, versions, password, Try again, make current, new version, archive) | done | `/departments/{id}/documents/{documentId}`; versions carry their page sizes (`pages`); 9 Vitest tests: the current version in the viewer with every version beside it, an older version opened and made current only after the dialog, the password field only while a version needs one (wrong password shown), Try again after a passing failure while the current version stays in view, read access gets the viewer, versions and downloads only, the email code and only the changed fields saved, archive only after confirming, a new version added with its instructions and key, a file already in the department never becomes a version |
| 4.11 | Deploy and live end-to-end check | done | `make check`: 403 backend, 125 frontend tests, build. Deployed; live database at 0015 (no role still holds `files.*`; nine hold `documents.send`). Headless Chromium on https://hemanth.tail50655e.ts.net, all 9 steps passing: a new department with a held file uploads it, names it from the file and processes it to Ready; the same file again asks and Cancel adds nothing; the department lists it and the viewer paints the PDF (pdf.js worker from our origin) with byte ranges answering 206; a .docx version is converted by Gotenberg and becomes current when ready; v1 made current after the dialog; a locked PDF refuses a wrong password and opens with the right one; a scanned page is named; a Viewer reads and downloads with no edit actions or dropzones; at 390 px the viewer paints with no sideways scrolling |
| 4.12 | Review fix: a version can no longer stay Processing forever | done | Job kinds gain `on_dead`, run in the transaction that marks a job dead (backbone LLD §1.4 "Settling a dead job"); `document.process` uses it to fail the version as temporary. Tests: the last attempt raising, a failure while saving on the last attempt, and a worker dying on the last attempt each leave Failed with Try again (the latter two fail without the fix); kernel: the hook runs for both dead paths and commits with the dead mark, and a failing hook still leaves the job dead |
| 4.13 | Review fix: an older version ready late never overrides a person's choice | done | `promote_if_newest` promotes only when no higher-numbered version is ready (it compared only with the current version). Test: v2 failed, v3 current, a person picks v1, Try again on v2 finishes and v1 stays current (fails without the fix); the existing current-version tests still pass |
| 4.14 | Review fix: a Word file holding a PDF is recognised as Word | done | `detect_kind` checks the ZIP and compound-file signatures at offset 0 before looking for `%PDF-` in the first KB. Test: a .docx whose first stored part is a PDF uploads as `docx` (it was `pdf` without the fix); the other upload tests still pass |
| 4.15 | Review fix: one shared hook for the server's settings | done | `shared/api/useMeta` is the single `/api/v1/meta` query (key, fetch, cache policy); `usePasswordRules`, `useDocumentLimits` and the developer MetaPanel read through it instead of three copies. Test: two components reading password rules and document limits make one request; MetaPanel, auth and documents tests still pass |
| 4.16 | Review fix: the too-large message states the configured limit | done | `UploadPage` builds both size refusals (before sending, and the server's or proxy's 413) from `DOCUMENT_MAX_BYTES` via /meta instead of a written "50 MB". Test: with the limit at 20 MB a 413 says "Upload a file of 20 MB or less" (said 50 MB without the fix) |
| 4.17 | Review fix: uploads map error answers through the shared client rule | done | `shared/api/client.answerError` is the one mapping from an error answer to `ApiError` (with Retry-After) or `NetworkError` (a proxy's bare 502/503/504); `unwrap` and `uploadFile` both use it instead of the upload's own copy. Tests: a proxy's 502 reads "The upload didn't finish. Try again" with Try again (showed "Bad Gateway"), the hourly limit states "Try again in 10 minutes" (showed the raw title); the client's own tests still pass |
| 4.18 | Review fix: Try again decided by the kind of failure, and offered for an expired upload | done | Upload rows carry `canRetry`, set where the failure is classified (no answer, the hourly limit, a server fault, an expired upload) instead of matching message text. Try again sends the file again with a new idempotency key and keeps a typed name. Test: an upload expired before Add document offers Try again, sends the file again and keeps "Client letter" (no Try again without the fix); a refused file still gets none |
| 4.19 | Review fix: uploads only where the person can add documents, and they can be stopped | done | Transfers start only when the department is active and editable; each has an AbortController, aborted by the row's new Cancel and when the page is left (a development remount starts them again). Tests: files handed to an archived department send nothing, Cancel aborts that transfer only and leaving aborts the rest (both fail without the fix), and a handed-over file still uploads under StrictMode's double mount |
| 4.20 | Review fix: the viewer opens nothing once it has been left | done | The load effect checks for cancellation after pdf.js's dynamic import and before `getDocument`, so a viewer left or switched while pdf.js was still arriving leaves no document, worker port or range fetches open. Test: unmounting before pdf.js arrives calls `getDocument` never (it was called without the fix) |
| 4.21 | Review fix: switching versions shows no page of the previous one | done | `PageCanvas` releases its bitmap while there is no document for the current URL, as it already did off-screen. Test: after v2 has painted, switching to a v1 that is still loading empties the canvas (v2's page stayed without the fix) |
