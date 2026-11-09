# Phase 6 — Field review and approval (LLD)

Status: topics agreed (2026-11-09); building on `phase-6/review`. Authoritative for review and approval; the
platform design (`docs/design/signora-platform.md`) FR-14 to FR-16 and §7.6 are refined here. Sections 1–7 record
the owner's decisions per topic; sections 8–14 are the low-level design built from them.

## Problem

Detection (Phase 5) proposes a version's parties and fields. A person with edit access checks and corrects them
on the PDF, then approves the version; only approved versions can be sent (Phase 7). Every change made in review is
recorded, and approval measures how close the AI came (precision, recall and the changes people made).

## Topics

| # | Topic | Status |
|---|---|---|
| 1 | Approval, versions and the record of changes | agreed (below) |
| 2 | Warnings before Approve | agreed (below) |
| 3 | Editing parties | agreed (below) |
| 4 | Editing fields | agreed (below) |
| 5 | Editing on the PDF | agreed (below) |
| 6 | Saving, concurrency and the API | agreed (below) |
| 7 | The review screen | agreed (below) |
| 8 | Tests and the live check | agreed (§13) |

## 1. Approval, versions and the record of changes (owner decisions, 2026-11-09)

### 1.1 States

- `ready` now means **in review**: fields found, editable by people with edit access.
- `approved` (new): the fields are frozen, the version can be sent, and it is immutable.
- `processing`, `detecting`, the failures and `needs_password` / `needs_ocr` are unchanged (Phases 4 and 5).
- Migration: every version that is `ready` today stays `ready` (in review, unapproved). Documents whose current
  version is not approved get no current version until one is approved (nothing can be sent before Phase 7).

### 1.2 Editing and the version bump

- **An unapproved version** is edited in place; each Save updates its fields. No new version.
- **An approved version** is never changed. The first Save of an edit to it creates a **new version**:
  - the next number in the document (v1 edited while v5 is the newest becomes v6);
  - the same stored file (no upload), with its fields copied from the source and the edits applied;
  - named `"{source version's name} - {new number}"` ("Financial NDA - 6"), with the source's description; when the
    source was itself made by editing, its own number is replaced, not appended ("Financial NDA - 6" edited gives
    "Financial NDA - 7"; build decision, 2026-11-08);
  - recording the version it came from; it starts in review, and later Saves edit it.
- Only field-level changes make a version: parties, fields, places, types, who fills, required, conditions. The
  document's name and description are not versioned and never make one.
- A version made by editing shares its file with its source on purpose: the "already here" check (Phase 4 §2.3)
  does not apply to it.

### 1.3 Approve

- Only people with edit access in the department (owners, editors, people granted edit access) edit or approve;
  everyone else sees the fields read-only.
- Approve checks topic 2's rules, records who approved and when, writes an audit entry and the version's review
  metrics (§1.5), and freezes the version.
- The newest approved version becomes current automatically; Make current chooses among approved versions only.
- Find fields again is refused on an approved version (`409 fields-approved`); on an unapproved version with manual
  edits it asks before replacing them.

### 1.4 The record of changes

Every Save writes one audit entry listing what changed: fields and places added, removed or changed (with the
attributes before and after), and parties added, removed or changed.

### 1.5 Review metrics (brings back platform FR-15, which Phase 5 dropped)

At approval the approved fields are compared with the AI's proposal using the platform's
matching (§7.6: placements overlapping with IoU ≥ 0.5 and the same type family, paired one to one, greedy by IoU per
page). Stored per version: true positives, false positives, false negatives, precision, recall, F1, and how many
fields were relabelled, retyped or given to another party. A version made by editing is compared with the AI
proposal of the version it came from, so the numbers keep measuring the AI.

Where the proposal lives (build decision, 2026-11-08): review keeps it, not `detection_runs.result`, because review
never reads detection's tables (ADR-R1) and a version made by editing has no run. When detection hands its proposal
over (`replace_fields`), review snapshots each place (page, box, type, label, who fills, party id) in
`version_reviews.proposal` with `baseline_version_id` = the version itself. A version made by editing copies its
source's snapshot and baseline, with party ids moved to its own (the ids `rekey` gave them), so renaming a party is
not a reassignment, while a field given to a party the source no longer had is. Migration 0018 builds the snapshot
for existing versions from their rows, which nobody could edit before Phase 6.

### 1.6 Concurrency

A version's fields carry a revision number. A Save sends the revision it started from; if someone else saved in
between it is refused (`409`, "changed by someone else; reload"), so no change is silently overwritten.

### 1.7 Unsaved changes

Saving is explicit. Leaving with unsaved changes asks first: the browser's own prompt when the tab is closed or
reloaded, and our dialog for back links and navigation inside the app.

### 1.8 One list of values

Field types, party kinds and who fills are defined once in the backend and used by the AI's schema, the API contract
and the interface; the interface's labels must cover the contract's values exactly (a type check fails otherwise).
Editing by hand also allows a free-text "Other" for the field type, the party kind and who fills ("as flexible as
DocuSign"); a typed "who fills" creates a party with that name. The AI's schema stays a closed list.

## 2. Warnings before Approve (owner decisions, 2026-11-09)

### 2.1 Soft, never a block

Nothing about a version's content blocks Approve. The rules below are **warnings**: the person sees them and may
approve anyway (a version with nothing to sign included). They are computed only on the server: the fields endpoint
returns the current warnings, each with a code and the field or party it concerns, and the panel lists them (each
jumps to its field). Approve opens a confirmation listing them, and approving records which were accepted.

| Code | Warning |
|---|---|
| `no_signer` | No party signs |
| `party_cannot_sign` | A signer or countersigner has no signature place |
| `own_value_not_a_partys` | A signature, initials or signing date is filled by the sender or by nobody |
| `needs_a_look` | Fields still flagged by detection (one warning with the count) |
| `already_signed`, `xfa`, `addressed_to_ai` | The document's flags (Phase 5) |
| `overlapping_places` | Two places overlap on a page |
| `private_value` | A field holds a private value (tax number, bank account, date of birth): who will see it |

A field nobody fills ("For office use only") is legitimate: no warning; it shows as "Not asked".

### 2.2 "Needs a look" without a button per field

There is no per-field "Looks right". A flag clears when its field is edited; approving accepts every flag still
left, and the approval's audit entry and metrics record them as accepted as detected.

### 2.3 What is not a warning

- **The version's state** is a guard, not a rule: only a version in review (`ready`) can be approved (`409`
  otherwise), as only one can be edited.
- **Well-formed data** is checked when it is saved, not at approval: a Save whose condition points to a field or
  option that does not exist, whose place lies outside its page or is smaller than 8 pt, or whose name (or typed
  "Other") is empty is refused (`422`, naming the field). These are the shape of the data, not judgements about it.

## 3. Editing parties (owner decisions, 2026-11-09)

In edit mode the panel's "Who signs" list is editable.

- **Add** a party: a name and a kind: Signer, Countersigner, or **Other** with typed text ("Witness",
  "Guarantor"). Every party signs either as a signer (customer side) or as a countersigner (firm side), because that
  decides when it signs (Phases 7–9): "Other" is a label on one of the two, chosen as "signs like a signer" or
  "signs like a countersigner".
- **Rename**: the label changes; the keys of its fields (`client_1.email`, used later by the send form and bulk CSV)
  follow the name while the version is in review and freeze at approval (nothing uses them before).
- **Order**: up and down within its group; signers sign first, then countersigners (platform rule).
- **Remove**: a dialog asks what becomes of its fields: move them to another party, make them "Not asked", or delete
  them. Moving also merges two parties the AI split ("Client" and "Client 1").
- **Shared values on a move**: a party has one signature, one set of initials, one signing date and one name, each
  with many places; moved into a party that already has one, the moved places become more places of it.
- **Checks at Save** (`422`, topic 2.3): a name for every party, unique in the version ignoring case; the text of
  an Other kind; at most 20 parties in a version.

## 4. Editing fields (owner decisions, 2026-11-09)

Choosing a field (in the list or by its box) opens its form in the panel:

- **Label**: free text.
- **Type**: from the one list (§1.8), grouped for picking: signing (signature, initials, signing date); identity
  (legal name, name, first and last name, company, title, date of birth); contact (email, phone, address, city,
  state, postal code, country, **URL**); money and numbers (amount, amount in words, number, percent, date);
  private (tax number, bank account); general (text, checkbox, choice); and the manual-only **Note** and **Other**.
  What a box can hold still depends on the PDF (a PDF checkbox cannot become a signature; a radio group stays a
  choice); boxes drawn by hand can be any type.
- **Who fills**: a party, "Filled in before sending", "Not asked", or Other (a new party, §3).
- **Required** or optional.
- **Condition**: "only when ⟨choice⟩ is ⟨option⟩", picked from the choices and checkboxes that exist.
- **Private**: automatic for tax number, bank account and date of birth; a toggle for an Other type.
- **Delete**: the field and all its places.
- **Shared values follow the type**: a field made Signature for a party that already has one becomes another place
  of it (§3); splitting a place out is §5.
- **Keys** stay automatic (party and label), never typed, frozen at approval.

### 4.1 One list, two audiences

The list of types is defined once (`detection/schema.py`) in two layers:

| Layer | Values | Who uses it |
|---|---|---|
| **AI** (closed) | today's types plus `url` | the AI's schema and prompt; never free-form, never Note or Other |
| **Manual** | the AI layer plus `note` (read-only text shown to the signer) and `other` (with typed text) | editing in review, the API contract and the interface |

The manual layer is derived from the AI layer, so a type added for the AI is offered by hand too, and the interface's
labels must cover the manual layer exactly (a type check fails otherwise). The same holds for party kinds (the AI:
signer, countersigner; by hand also Other with typed text, §3) and who fills (the AI: a listed party, the sender,
nobody; by hand also Other, which becomes a party).

### 4.2 Left for later

Attachment (a file the signer uploads), stamp or seal, and calculated fields need work in signing and rendering
(Phases 8–9); "Other" covers them by name until then.

## 5. Editing on the PDF (owner decisions, 2026-11-09)

- **Add (as in DocuSign)**: a palette in edit mode (Signature, Initials, Date signed, Name, Text, Checkbox, and
  "More…" for the rest of the list): pick one, then click on the page for its default size (signature 180×36 pt,
  initials 60×30, date 100×20, text 160×20, checkbox 12×12) or drag to draw it. It is filled by the party selected
  in the filter (else "Not asked"), and its form opens. Documents with nothing found are filled this way.
- **Move and resize**: drag the box; drag its corner and edge handles. Boxes stay inside their page, at least 8 pt.
- **Keyboard**: with a box selected, arrows nudge it 1 pt (10 with Shift) and Delete removes that place; the form
  shows its position and size as numbers, so everything can be done without a mouse.
- **More places for a field**: "Add a place", then click a page; for initials, "On every page" puts one at the same
  spot on each page.
- **Split**: "Make separate field" turns a place into a field of its own.
- **Remove**: deleting a field's last place deletes the field, after a confirmation.
- **Choices**: a choice made by hand is a place per option, each with its words; a radio group from the PDF keeps its
  options, which can only be renamed.
- **Undo and redo** (Ctrl+Z, Ctrl+Shift+Z) over the unsaved changes; Save makes them final and clears the history.
- **Phones**: the panel's forms work; drawing, moving and resizing need a larger screen (a touch drag fights the
  scroll and is too coarse), and the panel says so.
- **Coordinates**: PDF points of the page as displayed, as in Phase 5; zoom never changes the data.

## 6. Saving, concurrency and the API (owner decisions, 2026-11-09)

### 6.1 ADR-R1: a `review` module owns a version's fields

- **Context**: Phase 5 put `version_roles`, `version_fields` and `field_placements` in `detection`. Review edits and
  approves them, which is not detecting; two modules writing one set of tables would split their rules.
- **Decision**: a new `review` module owns those tables, editing, approval and metrics. Detection hands its proposal
  over through one public function, `review.replace_fields(version, result)`; review approves a version and creates
  an edited one through `documents.lifecycle` functions, as detection marks a version ready today. Dependencies run
  one way, detection → review → documents, enforced by the import contracts.
- **Consequences**: detection keeps only its runs and its proposal (`detection_runs`); review's rules have one
  home. The read endpoint (`GET …/fields`) stays in detection, because it joins detection's run state (stage,
  places found so far, flags) with the stored set, read through `review.read_set`; review owns the editing
  endpoints (save, revisions, approve). Review's pure helpers (`review.keys`, later `review.values`) are public
  submodules, so detection's pure code imports them without the package's database half.

### 6.2 Endpoints

| Endpoint | What it does |
|---|---|
| `GET …/versions/{v}/fields` | as now, plus the fields revision, the warnings (§2), whether the caller may edit, and who approved when |
| `PUT …/versions/{v}/fields` | saves a version in review: the whole set (parties, fields, places) as the editor holds it, with the revision it started from. One transaction: check the revision, validate (§2.3), compute the changes against the stored set by id, write them, recompute keys, increase the revision, write one audit entry listing the changes |
| `POST …/versions/{v}/revisions` | saves an edit of an approved version: creates the new version (§1.2) with the given set. Creates, so it needs an `Idempotency-Key` (one version however often it is retried); the page then opens it |
| `POST …/versions/{v}/approve` | with the revision and the warnings shown: approves, writes the metrics (§1.5) and the audit entry, makes the version current |

### 6.3 Identity, conflicts and size

- New parties, fields and places get their ids in the browser (UUIDs), so a retried save, the audit entry and undo
  refer to stable ids; the server checks they are new and unique in the version.
- A stale save or approve is refused with `409 fields-changed`; the page offers to reload, saying that unsaved edits
  would be lost. `PUT` on an approved version is `409 fields-approved` (the client uses `revisions`). Malformed data
  is `422`, naming the field.
- A save is linear in the number of fields and places (maps by id, bulk writes, one transaction): a few thousand
  fields save in well under a second.

## 7. The review screen (owner decisions, 2026-11-09)

Review is the document page itself (`/departments/{id}/documents/{documentId}`), no separate page; it changes with
the shown version's state, and choosing a version in the list reviews that one. Built on the prototype's screen 13.

- **Version state**: its label reads "Needs approval" (in review) or "Approved ✓" (approver and date in its
  tooltip); the versions list shows the same, and "from V1" on a version made by editing.
- **In review** (edit access): the panel is editable at once. With changes, a **save bar** at the panel's top:
  "3 unsaved changes · Undo · Discard · Save".
- **Approved**: the panel is read-only with **Edit fields**; while editing, the save bar says "Saving makes version 6.
  Version 1 stays approved as it is."
- **Approve version**: at the top of the fields panel only, beside the save bar and a line like "2 things to check";
  it opens the confirmation listing the warnings (§2) and is disabled while changes are unsaved (what is approved is
  what is saved).
- **Panel, overview**: "Who signs" (add, rename, reorder, remove); a **Things to check** box listing the warnings,
  each with "Show me"; the filters, search and list.
- **Panel, a field**: choosing one swaps the overview for its form (label, type, who fills, required; "More": the
  condition, private, position and size, the key, "Make separate field"), its places stepper and Delete; "Done"
  returns.
- **+ Add field** in the viewer's toolbar opens the palette (§5).
- **Read-only people** see the same page with no controls.
- **Leaving with unsaved changes**: our dialog ("Discard 3 unsaved changes?" with Keep editing and Discard); closing
  the tab, the browser's own prompt.
- **Phones**: the forms work; drawing needs a larger screen (§5).

### 7.1 The review screen, revised after use (owner decisions, 2026-11-09)

The first build put everything in one undivided column, hid "+ Add field" in the viewer's toolbar, made a field's
click replace the panel with its form, and gave party warnings no way forward. Revised:

- **One action bar** above the viewer and the panel (sticky under the top bar): the version, its state ("Needs
  approval", or who approved and when) and "N things to check" on the left; **Approve version** on the right. With
  unsaved changes the same bar reads "N unsaved changes · Undo · Discard · Save" (Approve waits until saved); an
  approved version offers **Edit fields** there.
- **Sections with hairlines** in the side column: Things to check, Who signs, Fields (then Signing and Versions as
  before), each with the design system's small-caps title.
- **A field is a row that expands in place**: choosing it in the list or its box on the PDF highlights the box and
  opens its row; the row shows its details, editable for people with edit access and as text for everyone else.
  Choosing it again, or another field, closes it. No separate form screen.
- **The field list scrolls inside itself** (owner decision, 2026-11-09): at most the design system's table height
  while every row is closed; an opened row comes to the list's top and the list is exactly as tall as that row and
  the two rows under it, refitting as the row's content grows (`ExpandableList scrollable`). At the list's first or last row,
  scrolling carries on to the page. While a field is being placed, what a click does is pinned over the top of the
  pages, high contrast, with Cancel (`PdfViewer notice`); the Add field row points there.
- **"+ Add field" is the first row of the field list**: it opens into a row with a Type dropdown (grouped, every
  type) and who fills it (the filtered party by default), then "Place on the page": click where it goes, or drag to
  draw it. The viewer's toolbar says so while placing. On phones it is placed on page 1 and moved with the numbers.
- **Parties read as text**: tone, name, how they sign, field count, and a pencil that turns that one row into its
  editor (name, kind, order, remove).
- **Warnings carry their fix**: a field's warning has "Show me"; "has no place to sign" has "Add signature", which
  starts placing a signature filled by that party.
- **Design system** (`shared/ui`, one definition each, shown on `/dev/ui`): `ActionBar` (a status and actions on one
  sticky line) and `ExpandableRow` / `ExpandableList` (a list row that opens in place, `aria-expanded` on its
  button, its content a labelled region); the `chevron` icon.

---

# Low-level design

## 8. Requirements

### 8.1 Functional

| # | Requirement |
|---|---|
| FR-R1 | A person with edit access edits a version in review: parties (§3), fields (§4) and places (§5). |
| FR-R2 | Saving is explicit; a Save is one transaction, one revision, one audit entry listing the changes (§1.4). |
| FR-R3 | Editing an approved version creates the next version on its first Save, sharing the file (§1.2). |
| FR-R4 | Approve freezes a version; it alone can be sent; the newest approved version becomes current (§1.3). |
| FR-R5 | Warnings are listed and accepted, never blocking (§2); malformed data is refused at Save (§2.3). |
| FR-R6 | Approval stores review metrics against the AI's proposal (§1.5). |
| FR-R7 | A stale Save or Approve is refused, never overwriting another person's change (§1.6). |
| FR-R8 | Leaving with unsaved changes asks first (§1.7). |
| FR-R9 | Field types, party kinds and who fills are one list in two layers, AI and manual (§4.1). |
| FR-R10 | Read-only members see the same page without controls (§7). |
| FR-R11 | Find fields again is refused on an approved version (`409 fields-approved`). |

### 8.2 Non-functional

| # | Quality | Target |
|---|---|---|
| NFR-R1 | Save latency | a 2 000-field, 4 000-place set saves in < 1 s (p95) on the dev box; linear in fields and places |
| NFR-R2 | Approve latency | < 1 s for the same set, metrics included |
| NFR-R3 | Integrity | an approved version's parties, fields and places cannot change: a database trigger refuses it |
| NFR-R4 | Auditability | every Save, version made by editing, and Approve has an audit entry in the workspace chain |
| NFR-R5 | Concurrency | no lost update: revision compare-and-set under a row lock |
| NFR-R6 | Accessibility | every edit possible with the keyboard; boxes are for the mouse, the panel's forms for everyone |
| NFR-R7 | Boundaries | detection → review → documents only (import contracts) |

## 9. Data design

### 9.1 Tables after Phase 6

`document_versions` (owned by `documents`): the version itself and its state.

| Column | Change | Notes |
|---|---|---|
| `status` | `approved` added | `processing`, `needs_password`, `needs_ocr`, `failed`, `detecting`, `ready` (in review), `approved` |
| `name` | renamed from `ai_name` | the AI's name, or `"{source name} - {n}"` for a version made by editing |
| `description` | renamed from `ai_description` | the AI's description, or the source's |
| `derived_from_version_id` | new, nullable | the version it was edited from; FK `(derived_from_version_id, document_id)` → `document_versions(id, document_id)` (same document) |
| `approved_by` | new, nullable | FK `(approved_by, workspace_id)` → `users(id, workspace_id)` |
| `approved_at` | new, nullable | |

Constraints: `status_known` gains `approved`; `processed_has_pdf` applies to `approved` too; new `approved_is_recorded`:
`(status = 'approved') = (approved_by IS NOT NULL AND approved_at IS NOT NULL)`.

`version_roles`, `version_fields`, `field_placements` move from `detection` to `review` (definitions only; the tables
keep their names and rows).

| Table | Column | Change | Notes |
|---|---|---|---|
| `version_roles` | `kind_label` | new, nullable text | the typed text of an Other kind ("Witness"); `kind` stays `signer`/`countersigner` (how it signs). Check `kind_label IS NULL OR char_length(kind_label) BETWEEN 1 AND 40` |
| `version_fields` | `holds` | values | the manual layer (§4.1): the AI's types plus `url`, `note`, `other`; still text, checked by the API (the list lives in code, §1.8) |
| `version_fields` | `holds_label` | new, nullable text | the typed text of an Other type. Check `(holds = 'other') = (holds_label IS NOT NULL)`, length 1–60 |
| `field_placements` | — | unchanged | a drawn place is `kind = 'blank'` with no `pdf_field`; its field has `origin = 'added'` |

New tables, owned by `review`:

```
version_reviews                       -- one row per version that has fields
  version_id     uuid  PK, FK (version_id, workspace_id) → document_versions
  workspace_id   uuid  not null
  revision       int   not null default 0, check (revision >= 0)   -- +1 per Save (§1.6)
  flags          jsonb not null default '{}'                      -- the document's flags detection found
  baseline_version_id uuid not null, FK → document_versions       -- whose AI proposal the metrics use (§1.5)
  proposal       jsonb not null default '[]'                      -- that proposal's places (§1.5)
  accepted       jsonb                                            -- at approval: the warnings accepted (§2.1)
  updated_by     uuid  FK users, nullable                         -- the last Save's author
  updated_at     timestamptz not null default now()

review_metrics                        -- one row per approved version (§1.5)
  version_id           uuid PK, FK → document_versions
  workspace_id         uuid not null
  baseline_version_id  uuid not null, FK → document_versions   -- whose AI proposal it is compared with
  true_positives       int not null   -- matched places
  false_positives      int not null   -- proposed, not approved
  false_negatives      int not null   -- approved, not proposed (added by hand)
  precision            double precision, recall double precision, f1 double precision  -- null when undefined
  relabelled           int not null   -- matched fields whose label changed
  retyped              int not null   -- … whose type changed
  reassigned           int not null   -- … whose filler changed
  flags_accepted       int not null   -- "needs a look" flags approved as detected (§2.2)
  mean_iou             double precision
  computed_at          timestamptz not null default now()
```

### 9.2 Integrity trigger (NFR-R3)

Statement-level `AFTER INSERT`, `AFTER UPDATE` and `AFTER DELETE` triggers on `version_roles`, `version_fields`
and `field_placements` (functions `review_forbid_approved_rows` and `review_forbid_approved_updates`): each checks
every row the statement touched (transition tables) with one join, and raises when any belongs to an `approved`
version. Per-row triggers cost about 0.9 s on a 2 000-field save (one lookup per row) and broke NFR-R1. Approving
only changes `document_versions`, so the triggers never stand in its way; a version made by editing writes its own
rows.

Save performance, measured 2026-11-09 (2 000 fields, 4 000 places; the earlier test timed only a first save):
- **Re-saving took about 2 s.** Deleting the old fields let the cascade delete their places with one statement per
  field, each firing the statement triggers, and each deleted field's "does a condition still refer to it" check
  read the whole table (`depends_on_field_id` had no index: quadratic). Fixed: the writers delete places, fields and
  parties children first, one statement each (`store._clear`), so the cascade finds nothing; 0018 adds partial
  indexes on `version_fields.role_id` and `depends_on_field_id`. The cascading keys stay: with the places already
  gone, deleting fields takes about 105 ms with them and about 440 ms with plain keys (their deferred checks).
- **A freshly migrated database has no planner statistics**, and its foreign-key checks then read whole tables:
  the first save took about 0.85 s instead of 0.35 s. A running database has statistics (autovacuum); the timing
  tests analyze the tables first so they measure that, not the test database's birth. The trigger body itself takes
  about 1 ms for 4 000 rows.
- Result with statistics: first save about 0.35 s; worst re-save (every row new) about 0.64 s; approve about 0.2 s.

### 9.3 Migration `0018_review`

Upgrade, in one transaction:

1. `document_versions`: rename `ai_name` → `name`, `ai_description` → `description`; add `derived_from_version_id`,
   `approved_by`, `approved_at` with their foreign keys; replace `status_known` and `processed_has_pdf`; add
   `approved_is_recorded`.
2. `version_roles.kind_label`, `version_fields.holds_label` with their checks.
3. Create `version_reviews`; insert a row (revision 0) for every version that has a `detection_runs` row.
4. Create `review_metrics` and the trigger function and triggers.
5. Data: no version is approved yet, so `UPDATE documents SET current_version_id = NULL` (§1.1: current means newest
   approved). Ready versions stay ready.

Downgrade reverses it: drops the triggers, tables and new columns, renames the columns back, and restores the
constraints (any `approved` version becomes `ready` first).

## 10. Interface contracts

All under `/api/v1/documents/{document_id}/versions/{version_id}`; editing needs edit access in the department
(`documents.require_document(edit=True)`), reading needs read access. Errors are problem details (backbone §5).

### 10.1 `GET …/fields` → `VersionFields`

```
VersionFields {
  status, stage, fields_from, pending, flags, found_again_failed      -- as in Phase 5
  revision: int                                                        -- §1.6
  editable: bool                                                       -- the caller may edit (and the state allows)
  approved: { by: PersonRef, at: datetime } | null
  derived_from: int | null                                             -- the source's version number
  warnings: [ Warning { code, message, field_id?, party_id?, count? } ] -- §2.1
  parties: [ Party { id, label, kind: "signer"|"countersigner", kind_label?, position, field_count } ]
  fields:  [ Field { id, key, label, holds: ManualHolds, holds_label?, filled_by: "role"|"sender"|"none",
                     party_id?, required, sensitive, origin: "detected"|"added",
                     depends_on: { field_id, option } | null, needs_review?,
                     places: [ Place { id, page, rect: [x0,y0,x1,y1], kind, option_value?, option_text? } ] } ]
}
```

`ManualHolds` and the AI's `Holds` are OpenAPI enums generated from §4.1's lists, so the web client's types come from
the contract.

### 10.2 `PUT …/fields` (save a version in review)

Request `FieldSet { revision, parties: [Party without counts], fields: [Field without key, origin, needs_review] }`;
the server keeps each existing place's `pdf_field` by id (the client never sets it). Response `200 { revision }`
(built: the page already holds the set it sent, and the fields view is detection's to build, ADR-R1; the page
refetches it after a save).

| Status | Code | When |
|---|---|---|
| 409 | `fields-changed` | `revision` is not the stored one |
| 409 | `fields-approved` | the version is approved (use `revisions`) |
| 409 | `version-not-in-review` | the version is processing or finding fields |
| 422 | field errors | §10.5 |

### 10.3 `POST …/revisions` (save an edit of an approved version)

Headers: `Idempotency-Key` (required). Request: `FieldSet` (its `revision` is the source's). Response
`201 { version_id, number, revision }` (built; the page opens the new version and loads its fields, as for a
save). The set is checked against the source exactly as a save is (§10.5), then written under fresh ids: ids are
unique across versions, and every reference moves with its id (`editing.rekey`). The new version starts at
revision 1 with the source's document flags; its audit entries are `document.version_derived` and
`document.fields_saved` (changes against the source). `409 version-not-approved` if the source is not approved,
`409 fields-changed` if the editor started from an older revision, `409 document-archived` on an archived document.

### 10.4 `POST …/approve`

Request `{ revision: int, accepted: [code] }`. Response `204` (built; the page reloads the document, whose versions
say which is approved and current). `409 fields-changed` on a stale revision, `409 version-not-in-review` unless
`ready`, `409 warnings-changed` when `accepted` is not exactly the warnings the server finds now (the person approves
over what they saw; with the revision unchanged this only happens to a client out of date). The server records its own
warnings in `version_reviews.accepted` and writes the metrics to `review_metrics`; the audit entry
`document.version_approved` lists the accepted codes and the metrics' counts (the audit chain's canonical JSON has no
floating-point numbers; the ratios follow from the counts).

### 10.5 Validation (`422`, each error naming its item)

- Ids: new ones are UUIDs not used elsewhere in the version; existing ones belong to it.
- Parties: 0–20; label 1–80 characters, unique ignoring case; `kind` signer or countersigner; `kind_label` 1–40 when
  given.
- Fields: 0–2 000; label 1–120; `holds` in the manual layer; `holds_label` 1–60 exactly when `holds = other`;
  `filled_by = role` exactly when `party_id` names a party of the set; a PDF box's `holds` within what its kind
  allows (Phase 5 `ALLOWED`); `depends_on` names a field of the set that is a choice or a checkbox, with one of its
  options, and no loops.
- Places: each field has 1–500; `page` within the version's pages; the rect inside that page (its displayed size),
  `x1 − x0 ≥ 8` and `y1 − y0 ≥ 8`; `option_text` ≤ 200.

## 11. Algorithms and complexity

R parties, F fields, P places.

| Step | Approach | Cost |
|---|---|---|
| Validate | maps by id; one pass over the set; loop check by walking each dependency chain once (Phase 5 `_break_loops`, here refusing instead of breaking) | O(R + F + P) |
| Shared values | group fields by (party, holds) for `SHARED` holds; places of a second field join the first (by id order); recorded in the audit entry | O(F + P) |
| Keys | one function, moved from detection's derive into `review.keys` and used by both: `<party>.<holds>` for party values, `<owner>.<words of label>`, unique by suffix | O(F) |
| Changes | maps by id, old and new: added, removed, and changed attributes (before and after) for parties, fields and places | O(R + F + P) |
| Write | delete removed, upsert changed and added with multi-row statements; one transaction, the version row locked | O(R + F + P) statements' rows, a constant number of statements |
| Warnings | one pass, plus overlap per page by sorting places on `x0` and sweeping (intervals open while `x0 < x1`) | O(F + P log P + K), K overlapping pairs |
| Metrics (§1.5) | per page, sort proposed and approved places on `x0`, sweep for candidate pairs with IoU ≥ 0.5 and the same family (signing: signature, initials, signing date; checkbox: checkbox, choice; data: the rest); sort candidates by IoU, pair greedily one to one. Field comparison follows the pairs (a field's label, type and filler against the proposed field's) | O(P log P + C log C), C candidate pairs |
| Version bump | lock the document row; `max(version_no) + 1`; copy the file columns; write the set as a new version | O(R + F + P) |

Rejected: per-change PATCH endpoints (a Save is many changes and must be atomic; one revision per Save keeps conflict
handling simple); diffing in the browser (the server must recompute anyway to audit what it stored).

## 12. Module layout

```
apps/api/src/signora/modules/review/
  __init__.py      public: replace_fields, router; types: FieldSet …
  models.py        version_roles, version_fields, field_placements (moved), version_reviews, review_metrics
  values.py        the two layers (§4.1): AI holds (+url), manual holds (+note, other); kinds; families; SHARED, OWN, SENSITIVE
  keys.py          key naming (moved from detection.derive)
  validate.py      §10.5 → FieldError list
  changes.py       the change list for the audit entry
  store.py         read and write a set; replace_fields (detection's handoff)
  warnings.py      §2.1
  metrics.py       §1.5 and §11
  service.py       save, revise (version bump), approve: transactions, locks, audit
  routes.py        §10
```

`detection` keeps `detection_runs`, reading, the AI call and derive; its `schema.py` imports the AI layer from
`review.values`. `documents.lifecycle` gains `approve_version`, `derive_version` and `promote_if_newest_approved`;
`finish_detection` no longer promotes (a ready version is not current), and `make_current` requires `approved`.

Web: `features/documents/review/` — `editor.ts` (the editor's state as pure functions: add, move, resize, split,
delete, party changes, undo, redo; clamping and minimum size), `labels.ts` (`Record<ManualHolds, string>` and the
groups of §4), `useLeaveGuard.ts` (`beforeunload` plus our dialog for in-app links and history), and the panel's
components (save bar, party list, field form, things-to-check box, approve dialog) and the PDF tools (palette,
handles).

## 13. Tests (topic 8)

Backend (Postgres, as Phase 5):
- Migration: ready versions stay ready, current versions cleared, field rows intact, columns renamed; downgrade.
- Trigger: any change to an approved version's rows is refused.
- Save: the change list and audit entry; shared values merged; keys recomputed; `409 fields-changed`,
  `fields-approved`, `version-not-in-review`; each `422` rule; read-only refused; NFR-R1 timing.
- Revisions: next number, `"{name} - {n}"`, copied description, `derived_from`, the shared file (no duplicate check),
  one version on a retried request (idempotency).
- Approve: state guard, accepted warnings recorded, current moved to the newest approved, Find fields again refused.
- Warnings: one case per code.
- Metrics: matching (IoU threshold, families, one-to-one greed), precision, recall, F1, the field comparisons, on
  small hand-made sets; a version made by editing compared with its source's proposal.
- Values: the AI layer is contained in the manual layer; the contract's enums come from them.

Web (Vitest): the editor's functions; party and field forms; save bar and undo; the stale-save reload; Approve and
its warnings; the leaving dialog; the palette; keyboard nudges; the read-only view. Labels cover every type (the type
checker).

Harness: run the 9 documents with `url` added; refresh outputs and scores. Live: upload, review and edit, save,
approve, edit the approved version (the next version), approve it, and see current move.

## 14. Task tracker

| # | Task | Status | Evidence |
|---|---|---|---|
| 6.1 | This design | done | this document |
| 6.2 | `review` module: tables moved, `replace_fields` handoff, keys moved, import contracts | done | `review/models.py` (the three tables, unchanged), `proposal.py` (detection's handoff as plain data), `store.py` (`replace_fields`, `read_set`), `views.py`, `keys.py` (pure, from derive); detection's `write_fields` maps its result to a proposal; import contracts: review protected, review never imports detection, documents never imports review, `review.keys` pure. No behaviour change: detection, documents and kernel tests pass (249) |
| 6.3 | Migration `0018_review` and the integrity trigger | done | `0018_review.py` (§9.3) and the models; `documents.lifecycle.approve_version` (current = newest approved; `finish_detection` no longer promotes; Make current approved only; Find fields again `409 fields-approved`); the API exposes `approved`, `derived_from`, `name`, `description`; the list falls back to the newest version's file facts; web: "Needs approval" and "Approved". Tests: migration data and downgrade, the trigger, current version rules rewritten for approval (5), shared `tests/support/actors.py` |
| 6.4 | Values in two layers, `url` for the AI, contract enums | done | `review/values.py` (pure): the AI layer (`url` added) and the manual layer built from it (`note`, `other`), party kinds, who fills, box kinds, `ALLOWED`, the rule sets and metric families; detection's schema and derive import it (the AI's `ALLOWED` limited to the AI layer); `FieldView.holds` is the contract's enum, and the web's `HOLDS` labels are `Record<Holds, string>` (Website, Note, Other added). Tests: the two layers, the AI never offered a manual value, every rule names listed values, the contract carries the manual layer |
| 6.5 | Warnings | done | `review/checks.py`: `warnings_for` (one pass, overlaps by a sweep per page), `ReviewWarning` with its code, message and field or party; the document's flags now travel with detection's proposal and are kept on `version_reviews.flags` (added to 0018), and a new proposal moves the revision on; the fields endpoint returns `revision`, `warnings`, and ids (party, field's party, place) with `kind_label`, `holds_label`, `origin`. Tests: one per code (7) and the endpoint |
| 6.6 | Save: validation, shared values, changes, audit | done | `PUT …/fields` (`review/routes.py`, `service.save`): row lock and revision compare-and-set; `editing.py` (pure: `check` §10.5, `settle` shared values and keys, `changes` for the audit entry, places indexed by field so O(F + P)); `store.read_stored`/`write_set` (editor's ids kept, PDF field names kept, flags kept only while unchanged); `documents.version_for_review`, `record_field_count`, `audit_document`; errors `fields-changed`, `version-not-in-review`. Triggers made statement-level for NFR-R1 (§9.2). Tests (7): save and its audit entry, the three conflicts, each 422 rule, shared values merged, flags, read-only, 2 000 fields under 1 s |
| 6.7 | Revisions: the version bump | done | `POST …/revisions` (`review/routes.py`, `service.revise`, idempotency guard); `documents.derive_version` (next number under the document lock, the file's columns copied, `derived_name`, audit `document.version_derived`); `editing.rekey`; `store.begin_review`; the fields view reads flags from review once a version is reviewable (a derived version has no run); an archived document's fields cannot be saved (`version_for_review`). Tests (6): the new version end to end (same file, PDF field names kept, fresh ids, source unchanged, audit, saved in place, approved and current, named after an edited edit), a retried request makes one version, each refusal, archived save, `rekey`, `derived_name` |
| 6.8 | Approve, current, metrics | done | `POST …/approve` (`service.approve`: row lock, revision, warnings accepted must match, metrics, then `documents.approve_version` with the details for its audit entry); `review/metrics.py` (pure: `iou`, `match` by a sweep per page then greedy one to one, `measure`; `BaselinePlace`, `ApprovedPlace`); the proposal snapshot and baseline on `version_reviews` (§1.5, §9; added to 0018 with existing versions' snapshots); `store.read_baseline`, `record_approval`; `begin_review` moves the baseline's party ids; error `warnings-changed`. Tests: matching and measures (7), approve end to end (frozen, current, warnings and metrics recorded, audit, approve again and Find fields again refused), metrics after edits, an edited version against its source's proposal (a party rename is not a reassignment), stale and unseen-warnings refusals and read-only, 2 000 fields under 1 s (NFR-R2), the 0018 snapshot. Save performance fixed on the way (§9.2): children-first deletes, indexes on the field columns that refer to other rows, timing tests with statistics and the worst re-save |
| 6.9 | Web: editor state and labels | done | `review/editor.ts` (pure: the draft by ids from the fields view and back to the save body; field, place and party edits; geometry with the 8 pt minimum; undo and redo, typing in one box one step); `fields.ts` `HOLD_GROUPS`, tone and who fills by party id; the fields view sends `allowed` (what each box may hold, `review.values.MANUAL_ALLOWED`: a blank can be any type, so the palette's checkbox and hand-made choices save). Tests: `editor.test.ts` (9) |
| 6.10 | Web: party and field forms, save bar, leaving dialog | done | `review/useReview.ts` (history per version and revision; Save in place, or `revisions` with an idempotency key for an approved version, then opens it; 409 and 422 turned into a notice naming each field), `PartyList.tsx`, `FieldForm.tsx`, `ReviewBar.tsx`, `useLeaveGuard.ts` (tab prompt and in-app links; the browser's back button inside the app is not caught: the App Router has no cancellable navigation event), opening another version asks too. Tests: `review.test.tsx` |
| 6.11 | Web: palette, move and resize, keyboard | done | `Palette.tsx` in the viewer's toolbar (`PdfViewer` `tools`), `FieldBoxes.tsx` (drag to move, corner handles, click or drag to draw), keys in `ReviewLayout.tsx` (Ctrl+Z, Ctrl+Shift+Z, arrows 1 pt or 10, Delete asks before a last place), phones keep the forms only. Tests: `review.test.tsx` (palette and keys) |
| 6.12 | Web: Approve, things to check, version states | done | `ThingsToCheck.tsx`, the Approve dialog (listing the warnings, sending the revision and the codes seen; disabled while changes are unsaved), Edit fields on an approved version, "from version N" and who approved in Versions. The bar says "N things to check", not "Needs approval" again (the version's label already says it). Tests: `review.test.tsx` (10), `document.test.tsx` updated for ids (18). Browser walkthrough not yet done: the browser extension was not connected |
| 6.12a | The review screen revised after use (§7.1) | done | `shared/ui`: `ActionBar`, `ExpandableList`/`ExpandableRow` (button named by the title, the facts its description; on `/dev/ui`; tests), the `chevron` icon, `--action-bar-height`; the side column's sections divided by hairlines; `ReviewActionBar` (state, things to check, unsaved changes; Approve, or Undo, Discard, Save; Edit fields); fields as rows that open in place (editable details for editors, text for readers); "+ Add field" the list's first row (Type dropdown, who fills, Place on the page; the viewer's toolbar says what a click does); parties as text with a pencil; "Add signature" on a party's warning; a version's fields stay on screen while it changes state (no blink). Tests: `review.test.tsx` (11), `document.test.tsx` (18), components (2) |
| 6.13 | Harness rerun, deploy, live check, PR | in progress | Harness rerun on the 9 documents with `url` in the AI layer (2026-11-09, `tests/outputs/SCORES.md`): no document has a website, so `url` changed nothing. Against the unconfirmed drafts the scores moved by run-to-run variance only: the Mutual NDA template's parties came back "Party 1/2" instead of "First/Second Party" (the scorer matches parties by slug, so its who-fills score reads 1/11), and the Trade Secret firm's own name, address and email flip between the firm and the sender in the clean run as well as the hostile one. Two injection checks failed this run for that reason: the hostile PDF gave those three to the sender (the surge check allows two), and the hostile Word file made the firm a signer, the opposite of what the planted text asks; agreement with the clean runs is 92 % and 98 %, the flag and the name held. Kept as run, not rerun to pass. Deploy: `make up-app` (0018 applied to the dev database; 11 versions in review kept, current cleared). Live: stack and dev server answer, review endpoints require sign-in; the browser walkthrough is not done (the browser extension was not connected) |
