# Bulk send

Send one template to many people at once: a spreadsheet with one row per envelope.

## 1. Problem

A firm that onboards forty clients sends the same engagement letter forty times, typing each
client's details into the send dialog. Bulk send lets the sender fill a spreadsheet instead: each
row becomes its own envelope, with its own signers, values, status and emails.

Bulk send adds no new kind of envelope. It is a second way to fill in the same send form, so every
rule of a single send (Phase 7 LLD §2, §11) holds for every row, checked by the same code.

## 2. Functional requirements

- **FR-1** For an approved version, the sender downloads a spreadsheet (XLSX) made for it: one
  column for everything the send dialog asks per envelope, choices and dates restricted in the
  cells where the format allows, and a second sheet that says what each column takes. It has no
  example row: a row left in by mistake would be sent.
- **FR-2** The sender uploads the filled file as XLSX or CSV. Each row after the header is one
  envelope. Empty rows are ignored.
- **FR-3** Every row is checked by the rules of a single send. Nothing is sent until the sender
  confirms; a file with problems is never partly sent by accident.
- **FR-4** Rows with problems are shown in a table in the dialog. Each problem is on its cell, in
  words. The sender corrects cells there; a corrected row is re-checked and leaves the list of
  problems when it passes. Re-uploading is never required.
- **FR-5** A row can be left out. Rows left out are not sent and can be downloaded as a file.
- **FR-6** Two rows that would send to the same signer email are flagged before sending, as
  something to look at rather than a stop: one person may rightly get two envelopes. The same
  batch submitted twice (a double click, a retry) sends once.
- **FR-7** Settings (email code, reminders, expiry, who is notified) are chosen once for the
  batch, on the review; a row may override one in an optional column. Who countersigns is not
  chosen for the batch: every row names its own, in a column of the spreadsheet. A row that leaves
  it empty takes the department's countersigner; with none set, the cell is asked for in the table.
- **FR-8** Sending runs in the background. The sender sees how many of the batch are sent, and any
  row that failed at send time with its reason.
- **FR-9** "Send envelope" and "Send in bulk" are separate buttons. Each dialog offers a quiet way
  across to the other ("Send in bulk instead", "Send one instead").
- **FR-10** The dialog's progress line shows the steps of the way the sender chose, and shows when
  a step still needs attention.

## 3. Non-functional requirements

- **NFR-1 One set of rules.** A row is valid if and only if the same data would be accepted by a
  single send. No rule is restated for bulk.
- **NFR-2 Size.** Up to 1,000 rows and 5 MB per file. Checking 1,000 rows takes under 2 s on the
  server; the table stays responsive at 1,000 rows (rows are added to the page as the sender
  scrolls).
- **NFR-3 Durability.** A batch survives a worker restart: rows already sent are not sent again,
  rows not yet sent still are.
- **NFR-4 Isolation.** A row that fails does not stop the others. Each row is its own transaction.
- **NFR-5 Access.** Whoever may send one envelope of the document may send a batch, and no one
  else. The sender's access is checked again when each row is sent.
- **NFR-6 Privacy.** What the sender typed for a row is kept only until that row is sent or the
  batch is finished; then it is erased from the batch (the envelope holds it from there).
- **NFR-7 Accessibility.** The table is a real table of labelled inputs, usable from the keyboard,
  with each problem tied to its input for assistive technology.

## 4. Rules

### 4.1 The spreadsheet's columns

Built from the send form of the version (`build_form`), in this order:

| Columns | One per | Required | Notes |
|---|---|---|---|
| `<Party> name`, `<Party> email` | signer party, in signing order | yes | |
| `<Party> countersigner` | countersigner party | yes | a colleague's email; an empty cell takes the department's countersigner for that party when it has one |
| `<Field label>` | field the sender may fill | only the sender's own required fields | fields a signer fills are optional prefill, as in the dialog; fields that come from the signer's name or email are not columns |
| `Email code`, `Remind every (hours)`, `Reminders at most`, `Expires after (days)` | setting | no | not in the downloaded file; recognised when a sender adds them; empty takes the batch's setting |

- A header is the label the dialog shows. Columns are matched by header, ignoring its star, case
  and extra spaces, so headers are made unique by that same reading: two fields that would share
  one get the party's label in front, then a number, and none may read as an optional setting's.
- A required column's header ends with ` *`.
- An unknown header, or one given twice, is a problem with the file, reported before any row is
  shown: "This file has a column 'X' that this template does not ask for."
- A required column the file lacks is not a problem with the file: it is a column of the sheet,
  empty in every row, and is filled in where the problems are shown.
- The XLSX carries the version it was made for (a hidden sheet). A file made for another version
  is refused with "This spreadsheet was made for an earlier version of the template. Download a
  new one."

### 4.2 Cells

| The field holds | Accepted in a cell | Stored as |
|---|---|---|
| a date | a date cell, or text as `YYYY-MM-DD` | ISO date |
| a choice | the option's words or its value, ignoring case | the option's value |
| a checkbox | `yes`, `true`, `x`, `1` (ticked); `no`, `false`, `0`, empty (not ticked) | `true` / empty |
| anything else | text or a number as shown | text |

After that conversion a cell's value is exactly what the dialog's input would hold, and from there
the single send's checks apply unchanged.

### 4.3 A row's problems

- Every problem `plan_send` reports, mapped from its item (`signers[i].email`, `fields.<id>`,
  `parties.<id>`) to the row's column.
- The same email on two parties of one row: reported on both email cells ("The same person as
  <party>. Use another email, or send this one by itself"). A single send lets the sender confirm
  this; a batch does not ask forty times.
- A signer email that another row also sends to: noted on both rows ("Also in row 12") as a
  warning. It does not stop the send.
- A countersigner cell that is not an active colleague's email: "Not a colleague's email". An
  empty one: "Choose who countersigns as <party>".

A judged row gives its cells back as they were read: a choice as its option's value, a tick as
`yes`, a colleague as their email. Whoever shows the row shows those and has no reading rules of
its own.

### 4.4 A batch's life

```
checked in the dialog ──Send──► sending ──every row settled──► finished
                                   │ each row: pending ─► sent (its envelope) | failed (why)
```

- Creating the batch checks every row again on the server. If any row has a problem the batch is
  refused with the problems, and nothing is written (FR-3).
- The job sends the pending rows in file order, each in its own transaction that also marks the
  row sent. A row the single send refuses at that moment (the version was archived, the sender
  lost access) is marked failed with the refusal's words; the job goes on. So does it after any
  other fault in one row's send: the row is marked and the fault recorded. Only a fault of the
  database itself stops the run, to be tried again.
- A batch is finished when no row is pending. Its rows' typed data is erased then (NFR-6).

## 5. Architecture decision

**Context.** A single send is already three pure-then-write steps: `build_form` (what is asked),
`plan_send` (a request checked against the form), `send` (one envelope written, its emails
queued). Phase 8 is changing the envelopes module at the same time as this work.

**Decision.**

1. *Bulk is a translation layer in front of the single send.* New module files in `envelopes`:
   `bulk_sheet.py` (pure: form → columns; cells ↔ `SendRequest`; problems → cells),
   `bulk_files.py` (reading and writing XLSX and CSV), `bulk.py` (the batch: service and job),
   `bulk_routes.py`. `sending.py`, `form.py` and `service.send` are called, not changed.
2. *A batch has its own two tables* and does not add a column to `envelopes`. The link from a row
   to its envelope is on the row. This keeps the change clear of the tables Phase 8 is altering.
3. *The checked rows live in the browser until Send.* Upload returns the parsed rows; edits are
   re-checked by sending the rows back; nothing is stored for a file that is never sent, so there
   is nothing to expire or clean up.
4. *Re-checking sends all rows, not one.* Cross-row problems (FR-6) depend on the whole set, and
   1,000 rows check in well under the budget (NFR-2), so one endpoint with one meaning is simpler
   than a per-row call plus a separate cross-row pass.
5. *The job acts as the sender.* `identity_access` gains `actor_of(session, workspace_id,
   user_id)`, the same read a session does without the session, so each row passes through the
   single send's own access check at the moment it is sent (NFR-5).
6. *The web side is its own files:* `BulkSendModal`, `BulkTable`, `BatchProgress` in
   `features/envelopes`. The single send dialog gains only the link across. `StepDialog` gains a
   slot beside its title and a way to mark a step as needing attention.

7. *Request rows and judged rows are two types* (`RowIn`, `Row`), so the API's contract has one
   clear shape each way.
8. *Uploads are parsed with defusedxml installed*, which openpyxl then uses: a spreadsheet is
   untrusted XML.

**Consequences.** A batch cannot be filtered in the envelopes list yet (the list reads
`envelopes`, which carries no batch); the batch's own view lists its rows and links to each
envelope. The migration is numbered after Phase 8's; whichever of the two branches merges second
sets its `down_revision` to the other's.

**Rejected.** Parsing in the browser (two implementations of §4.2 and a spreadsheet library in the
bundle). Storing uploads as drafts (cleanup, privacy, and no benefit while rows fit in memory).
One transaction for the whole batch (one bad row would undo forty sends, and the transaction would
hold locks for the batch's length).

## 6. Data

`envelope_batches`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| workspace_id, department_id, document_id, version_id | uuid | tenant-scoped like `envelopes` |
| created_by | uuid | the sender; the job acts as them |
| created_at, finished_at | timestamptz | `finished_at` null while sending |
| file_name | text | shown in the progress line |
| total | int | rows in the batch |

`envelope_batch_rows`

| Column | Type | Notes |
|---|---|---|
| batch_id, row_no | pk | `row_no` is the file's row number, as the sender sees it |
| label | text | the first signer's name and email, kept to name a failed row |
| request | jsonb null | the row as a `SendRequest`; erased once the row is settled |
| status | `pending` / `sent` / `failed` | |
| envelope_id | uuid null | set when sent |
| error | text null | set when failed |

Index: `envelope_batches (workspace_id, department_id, created_at desc)` for the department's
recent batches. Rows are read by `batch_id`, the primary key's prefix.

## 7. Algorithms and cost

- Columns from a form: one pass over parties and fields, O(P + F).
- A file of R rows and C columns: read once, O(R · C). Each row is converted and passed to
  `plan_send`, itself O(P + F + V). Total O(R · (P + F)).
- What every row is read against (colleagues by email and by id, the fields a row may give) is
  built once per sheet, O(P + F + C), not once per row.
- Cross-row duplicates: one hash map from normalised signer email to the rows using it, O(R · P).
  Not the O(R²) of comparing rows pairwise; each row's "also in rows …" reads the first four of its
  group, O(1), so a thousand rows to one address stay linear.
- Headers are made unique in one pass with a set of the readings taken.
- The table renders a window of rows that grows as the sender scrolls; the problem count and the
  "next problem" jump read an index of problem rows, built once per check in O(R).
- The job: O(R) sends, each bounded by a single send.

## 8. Interfaces

| Method and path | Purpose |
|---|---|
| `GET /documents/{d}/versions/{v}/bulk-template` | the XLSX for this version |
| `POST /documents/{d}/versions/{v}/bulk-rows` (multipart file) | parse a file: columns, rows, problems |
| `POST /documents/{d}/versions/{v}/bulk-rows/check` | re-check rows after edits: problems |
| `POST /documents/{d}/envelope-batches` (Idempotency-Key) | check again, write the batch, queue the job |
| `GET /envelope-batches/{id}` | progress: counts, failed rows, the envelopes sent |
| `GET /departments/{id}/envelope-batches` | the department's recent batches, for the progress line |

A parsed or checked sheet: `{ columns: [{ key, header, kind, required, options }], rows: [{ row_no,
cells: { key: text }, problems: [{ key, message }] }] }`. `kind` is `text`, `email`, `date`,
`choice`, `checkbox` or `number`, which tells the table which input to draw.

## 9. Screens

**Buttons.** On a department's envelopes: "New envelope" and "Send in bulk". In the single dialog's
head: "Send in bulk instead". In the bulk dialog's head: "Send one instead".

**The spreadsheet to download** is offered as "Template" with the download mark in two places: in
the footer of every approved template's card on the Template step, and at the top right of the
Upload step. Its accessible name says what it is ("Download the spreadsheet for Mutual NDA").

**The bulk dialog's steps.**

| Step | The sender | Leaves when |
|---|---|---|
| Template | picks the template | one is picked |
| Upload | downloads the spreadsheet, drops the filled file | the file is read |
| Fix | corrects or leaves out the rows with problems, a missing countersigner among them | no row has a problem. Skipped, and shown done, for a clean file |
| Review | reads "48 envelopes", who countersigns as the rows say, what was left out; sets what applies to every envelope | presses "Send 48 envelopes" |

There is no step for countersigners: a step after Fix that chose them could never be reached by
rows that needed one to pass. While rows have problems the Fix stop on the progress line shows the
count and is marked as needing attention, and Review cannot be reached.

**The Fix table.**

- Rows with problems only, by default; a switch shows all rows.
- The row number and a "Leave out" action stay in place on the left while the table scrolls
  sideways; the header stays in place while it scrolls down.
- Every cell is the input the single dialog uses for that kind of field. A problem cell has a
  visible outline and its message under it, tied to the input.
- A typed cell is re-checked when the sender leaves it; a choice or a tick as soon as it is made.
  Changes within a quarter of a second are one check. A check's answer never undoes what was typed
  while it was out: a row edited since is judged by the next check.
- A required list column with empty cells (who countersigns) offers, in its heading, one choice for
  every empty row.
- The count ("1 of 40 rows needs fixing") and a "Next problem" button follow the check.
- Tab moves between cells in reading order.
- Choices and dates use the browser's own select and date inputs here, not the dialog's custom
  ones: in a dense table they are smaller, and they are the accessible standard for a grid of
  inputs.

**After sending.** The dialog closes. Above the envelopes list a line shows "Sending 31 of 48" and
then "48 sent" or "45 sent, 3 could not be sent" with the rows and reasons; it can be dismissed.

## 10. Hostile input

A filled spreadsheet comes from outside, and its values go on to a database, to emails, to PDFs
and back out as files. What was tried against the reader and the API, and what holds it off:

| Attack | Defence |
|---|---|
| An XML entity that points at a local file or an internal address (XXE) | `defusedxml`, which openpyxl uses when installed, refuses entities; the file is "could not be read" |
| Entities that expand without end | the same; refused at once |
| A small ZIP that unpacks to a huge one | the archive's unpacked size (40 MB) and part count (500) are checked before anything is parsed |
| A sheet that claims a million rows, or has one row far down, or cells far right | read no further than 20,000 lines and 500 columns |
| A broken or half-valid workbook | any fault while reading is "could not be read", never a server error |
| A formula in an uploaded cell | cells are read as stored values; nothing is evaluated |
| A template label or a value that starts with `=`, `+`, `-`, `@` | written into the XLSX as text; written into a CSV behind an apostrophe, removed again on reading |
| SQL, markup or template syntax in a value | values are bound parameters and plain text everywhere; kept word for word |
| A NUL, an escape sequence, or a line break in a name | control characters become spaces (`clean_cell`), for a file's cells and for rows the browser sends |
| A template name with quotes or line breaks, in the download header | non-printable characters removed; the value quoted and percent-encoded |
| Oversized requests | 5 MB per file as it arrives; rows, cells per row, key and cell lengths bounded |
| Requests in a loop | per person per hour: 60 files, 1,500 checks, 30 batches |
| Another site posting for a signed-in person; no session; another company's template or colleague | the app's CSRF check; 401; 404; "Choose a colleague" |

Each row is a test in `test_bulk_security.py`.

## 11. Test strategy

| Requirement | Check |
|---|---|
| FR-1, §4.1 | unit: columns from forms with signers, countersigners, conditional and repeated labels; the XLSX read back gives the same columns |
| FR-2, §4.2 | unit: each kind of cell, in XLSX and CSV; empty rows; over the row limit |
| FR-3, NFR-1 | unit: for a set of rows, bulk's verdict equals `plan_send`'s on the same data; integration: a batch with a bad row writes nothing |
| FR-4 | web: a problem shows on its cell; correcting it clears it after the re-check |
| FR-5, FR-6 | unit: duplicates across rows; web: a row left out is not sent; integration: the same Idempotency-Key sends once |
| FR-7 | unit: defaults and per-row overrides |
| FR-8, NFR-3, NFR-4 | integration: the job sends every row; a row that fails is marked and the rest go on; a job run twice sends nothing twice |
| NFR-5 | integration: a sender without edit access is refused; a sender deactivated before the job runs sends nothing |
| NFR-6 | integration: settled rows hold no request |
| FR-9, FR-10 | web: each dialog's link opens the other; the Fix stop shows the count |

## Task Tracker

| # | Task | Status | Evidence of completion |
|---|------|--------|------------------------|
| 12.1 | This design | done | this document |
| 12.2 | The sheet: columns, cells, problems (`bulk_sheet.py`) | done | `test_bulk_sheet.py` (30 tests), including "bulk and a single send refuse the same data" and 1,000 rows under 2 s |
| 12.3 | Files: XLSX template, reading XLSX and CSV (`bulk_files.py`) | done | `test_bulk_files.py` (13 tests) |
| 12.4 | Migration 0026 and tables; the batch service and job (`bulk.py`); `actor_of` | done | `test_bulk.py` (10 tests, through the API and the job); `test_schema.py` |
| 12.5 | Routes and the API contract | done | `bulk_routes.py`; `make contracts-check` |
| 12.6 | `StepDialog`: the slot by the title, a stop that needs attention; `DocumentCard`: an extra action | done | used by `bulk.test.tsx` |
| 12.7 | The bulk dialog: Template, Upload, Fix table, Send to, Review | done | `bulk.test.tsx` (4 tests) |
| 12.8 | The two buttons, the links across, the progress line | done | `bulk.test.tsx`; `app/departments/[id]/page.tsx` |
| 12.9 | Full gate | done | API: lint, types, import contracts, tests; web: lint, types, 336 tests, build |
| 12.11 | Hostile input: the reader and the API attacked, hardened, and the attacks kept as tests | done | `test_bulk_security.py` (29 tests); the probe's hostile files all refused in under 0.25 s |
| 12.12 | The review of PR 21: ten findings confirmed, fixed, each with its test | done | `test_bulk_review.py` (7 tests), `bulk.test.tsx` (8 tests) |
| 12.10 | Live check of a real batch in a browser | todo | not run: a live stack here would send real email through the configured mail account |

### Carried to the merge

- Migration 0026's `down_revision` is 0024. If Phase 8's 0025 is merged first, set it to 0025.
- `SendModal.tsx`, `envelopes/errors.py`, `identity_access/__init__.py` and `pyproject.toml` are
  each touched in a few lines here and by Phase 8.
