# Phase 5b — Detection findings from flat-document testing

Parent: [`05-detection.md`](05-detection.md) · Recorded 2026-11-11 · Status: **open, to be fixed together**

Field detection was tested on documents with no form fields, whose places to fill are printed lines (`____`), and on
the flat twins of fillable forms. This document lists what was found, the document and test that show each finding,
and the proposed fix, so all of them can be designed and fixed in one pass.

## Test documents

Third-party documents stay local (`tests/fixtures/documents/` is git-ignored, Phase 5 §7.4); regression tests use
generated documents that reproduce the same shapes.

| # | Document | Kind | How it was made | Where |
|---|---|---|---|---|
| D1 | Basic Non-Disclosure Agreement (NonDisclosureAgreement.com, © 2020) | native flat PDF, typed underscores, 2 pages | as received | `tests/fixtures/documents/` · run in `tests/outputs/Basic Non-Disclosure Agreement.pdf/` |
| D2 | Unilateral Non-Disclosure Agreement (NonDisclosureAgreement.com, © 2018) | native flat PDF, typed underscores, 2 pages | as received | `tests/fixtures/documents/` · run in `tests/outputs/Unilateral Non-Disclosure Agreement.pdf/` |
| D3 | California DMV REG 135, bill of sale | fillable (68 widgets) | [dmv.ca.gov](https://www.dmv.ca.gov/portal/uploads/2020/06/reg135.pdf) | not yet in fixtures |
| D4 | Utah TC-843, bill of sale | fillable (31 widgets) | [tax.utah.gov](https://tax.utah.gov/forms/current/tc-843.pdf) | not yet in fixtures |
| D5 | Florida HSMV 82050, notice of sale / bill of sale | fillable (40 widgets) | [flhsmv.gov](https://www.flhsmv.gov/pdf/forms/82050.pdf) | not yet in fixtures |
| D6 | Simple Independent Contractor Agreement, a one-page template | fillable (21 widgets) | a free template site | not yet in fixtures |
| D3f, D4f, D6f | flat twins of D3, D4, D6 | flat PDF | every widget removed with PyMuPDF (`page.delete_widget`), the printed page kept | not yet in fixtures |
| D7 | UL Lafayette Non-Disclosure Agreement (Revised 11.2010), lengthened to 14 pages by repeating its clauses and opening paragraph | flat PDF exported from a word processor: no underscores in the text, every line drawn | as received | `tests/fixtures/documents/ULL_Non-DisclosureTemplate11-2010_formfill.pdf` |

## Results so far

| Document | Fields from | Places on the page (counted by eye) | Found | AI answer |
|---|---|---|---|---|
| D1 | blanks | 11 | 11 | all right; 1 call, 11.2 s, no problems left |
| D2 | blanks | 18 | 18 | all right; 1 call, 16.5 s, no problems left; Recipient signs, Company countersigns; the date split into day, month, year |
| D6f | blanks | 22 (fillable twin) | 23 | not run |
| D3f | blanks | 33 (fillable twin) | **6** | not run |
| D4f | blanks | 26 (fillable twin) | **6** | not run |

| D7 | **none** | 34 (31 drawn lines, 3 unmarked) | **0**: no AI call, the version would be ready with no fields | see below |

Runs used `gpt-6-luna` at `AI_REASONING_EFFORT=medium` (the `.env` value; see F8).

### D7 ground truth and an experimental run

**Ground truth** (read in full): the opening paragraph "by and between ⎵, a ⎵, whose address is ⎵" appears 9 times
(pages 1, 3, 4 ×2, 5 ×2, 11, 12 ×2); each gap is a 25 pt underlined run of spaces: the other party's name, its kind of
entity and its address. The signature block (page 14): the other party's `By:` (drawn line), `NAME:` and `TITLE:`
(blank space, no line), `DATE:` (drawn line); UL Lafayette's `By:` (drawn line), `NAME: Dr. Carolyn Bruder` and
`TITLE: Interim Provost` printed, `DATE:` (drawn line); a heading slot above the other party's column (no line).
Expected values: one name, one kind of entity, one address (each in 9 places), the other party's signature, printed
name, title and date, UL Lafayette's signature and date. Roles: the other party signs, UL Lafayette (whose template
it is) countersigns.

**Experimental run** (a scratch script, not product code): the 31 drawn lines were turned into blanks the crude way
F1 proposes, then the product's own layout, `ask` and `derive` ran unchanged.

| Measure | Value |
|---|---|
| Read (with drawn lines) | 301 ms, 31 places |
| Message | 59,023 characters, 681 layout lines |
| AI call | 1 call, 29.5 s; 16,454 input tokens, 3,228 output (1,115 reasoning); no problems, no repair |
| Cost at `gpt-6-luna` list price ($0.10 input / $0.50 output per 1M tokens) | **$0.0033** (D1 $0.0011, D2 $0.0014) |
| Roles | `party_1` signer, `ul_lafayette` countersigner: right |
| Name, description | "UL Lafayette Non-Disclosure Agreement", correct description |
| Party name | one value in 9 places: right |
| Kind of entity, address | **9 separate values each** (`address`, `address_2` … `address_9`): see F11 |
| Signatures, signing dates | right parties; boxes 13 pt tall (F2) |
| Printed name, title (no line) | found by the AI as extra fields: right meaning, **placed on the words "NAME:" and "TITLE:"** (F10) |
| UL Lafayette's printed name and title | not asked: right |
| Heading slot above the other party's column | not found (unmarked, topic 8) |

---

## Findings

### F1 — Lines drawn as graphics are not found (high)

**Seen in:** D3f (33 drawn horizontal lines, 6 typed underscore runs: 6 found), D4f (12 drawn lines and 12 thin
filled bars, 6 typed runs: 6 found), D7 (31 drawn lines, no underscores in its text: **0 found**, no AI call; in the
interface the version is ready with "We couldn't find places to fill or sign").

**Cause:** `blanks.find_blanks` reads only the text layer: underscore runs, placeholders and checkbox glyphs (§2.4).
A blank is a visual convention, an empty space with a line under it, and the reader recognises it only when the line
is made of `_` characters, which is how Word happens to make one. A word processor's underline on spaces (D7: the
text holds only spaces or zero-width spaces where the lines are), a layout tool's rule and a government form's drawn
line have no text, so they are invisible to it. Topic 8 covers places "marked by nothing"; a drawn line is a mark,
and no topic covers it.

**The rule: a line with nothing written on it.** What lies above a drawn line decides whether it is a blank, measured
on D1 and D7:

| Above the drawn line | Example | What it is | Blank |
|---|---|---|---|
| nothing, spaces, zero-width or invisible characters | D7 pp. 1–12 (spaces), D7 p. 14 (`U+200B`) | a writing line | **yes** |
| visible words | D1 p. 1 "Disclosing", "Receiving" | an underlined word (emphasis, a link) | no |
| typed underscores | D1 p. 2 | the same blank, already found from the text | no (not doubled) |

**Proposed fix:** a fourth kind of mark in `blanks.py`, beside underscores, placeholders and checkbox glyphs:

1. **Candidates**: from `page.get_drawings()`, stroked horizontal lines and filled rectangles at most 2 pt tall and at
   least 20 pt wide.
2. **Only the empty stretches**: the words on the text row just above the line, within its span, are found through
   the existing `RowIndex`; a word counts when its centre lies over the line, and a word made only of whitespace,
   zero-width characters (`U+200B`–`U+200D`, `U+2060`, `U+FEFF`) or soft hyphens counts as empty. The line is cut where
   visible words sit, and each remaining stretch of at least 20 pt is a candidate, so one underline drawn under
   "Name:␣␣␣␣␣" yields the stretch after the label.
3. **Not a blank**:
   - under a form field or under a blank already found from the text (typed underscores);
   - a table border: its ends meet vertical lines;
   - a rule: wider than 80 % of the page's text width, or in the top or bottom margin at the same position on every
     page (a header or footer rule).
4. **Merged and sized** as underscore runs are: pieces on one row closer than 6 pt are one blank; the box is the line
   with the text line above it (F2 then grows signatures and initials).
5. **Labels and layout** by the same `PageText` code as other blanks; the layout text shows `⟦fN⟧` where the spaces
   were.

Nothing after the read stage changes. A version read before the fix is detected again from the document page (Find
fields again, §1.3) while it is not approved.

**Edge cases and how each is treated:**

| Case | Treatment |
|---|---|
| an underline over a label and the spaces after it | the empty stretch after the label only (step 2) |
| underlined words: headings, links, defined terms | not a blank: visible words above |
| a line under typed underscores | not doubled (step 3) |
| header and footer rules, section separators | not a blank (step 3) |
| ruled tables | not a blank (step 3) |
| a form-style table whose empty cell has only a bottom line | a blank, flagged "check its position": often a real place to fill |
| dotted or dashed lines (`........`, `- - -`) | not covered: dot leaders in contents tables would be false blanks; left to topic 8 |
| boxes drawn as rectangles (a drawn `□`, comb boxes) | not covered: a separate mark, recorded for later |
| lines inside an image, scanned pages | not covered: scans are blocked as needing OCR (Phase 4) |
| white or hidden text above a line | accepted risk |

**Backstops for a wrong candidate:** the AI reads every marker in its sentence; a drawn-line blank the AI says
**nobody fills** is dropped with a note in the proposal rather than stored as a field (a typed blank keeps today's
treatment); every result is reviewed and approved by a person before it can be sent.

**Test cases:**
- Unit (generated PDF): underlined spaces after "Name:", "Date:" and under a "Signature" heading (found); an
  underline over "Name:␣␣␣␣" (one blank, after the label); underlined words and a link (none); a line under typed
  underscores (not doubled); a ruled table (none); a full-width rule and a footer rule on every page (none); a line
  under a form field (none); spaces made of `U+200B` and `U+00A0` (found); a drawn-line blank the AI says nobody fills
  (dropped, noted).
- Corpus: D7 finds its 31 lines; D3f and D4f find every place their fillable twin has (33 and 26, less the buttons);
  D1 still finds exactly 11 (its underlined words and doubled line are not blanks).

### F2 — Signature boxes on flat documents are one text line tall (high)

**Seen in:** D1 (12.3 pt), D2 (13.4 pt), the Word trade-secret NDA (12.3 pt). Fillable documents for comparison:
Mutual NDA 28.8 pt, trade-secret NDA form 23.9 pt.

**Cause:** a blank's box is the bounding box of its underscore text (`blanks._runs`); nothing changes it once the AI
says it holds `signature` or `initials`. `SignatureMark` scales a mark to its box's height: a typed signature is drawn
at 0.7 × height (≈ 9 pt, smaller than the 11 pt body text) and a drawn one is squeezed into a 13 pt strip, though the
page leaves 30–40 pt of free space above each signature line.

**Proposed fix:** in `derive`, where `holds` is first known: for a `blank` placement holding `signature` or
`initials`, grow the box upward into the free space above the line, up to the nearest text or another field, capped
at about 36 pt, keeping the line as its bottom edge so the mark sits on the line. Fillable signature boxes are left
as their author drew them.

**Test cases:**
- Unit: a signature line with 40 pt free above becomes 36 pt tall, bottom unchanged; with a heading 20 pt above it
  stops below the heading; a `full_name` blank on the same layout keeps its height; a form-field signature box is
  unchanged.
- Corpus: D1, D2 signature boxes ≥ 24 pt tall, bottom edge equal to the read stage's.

### F3 — Labels above signature and name lines are out of reach (medium)

**Seen in:** D2: f13–f18 (two signatures, two printed names, and their dates) have no `label_above`; "Company
Representative's Signature" sits ~45 pt above its line and "Print Name" ~35 pt above, beyond `LABEL_GAP = 18`
(`page_text.py:31`). The AI still answered correctly from the layout text.

**Cause:** one gap for every label above, tuned for form fields whose caption sits right on top of them.

**Proposed fix:** for a blank with nothing to its left, look further up (about 48 pt) for the nearest line that
overlaps it horizontally, stopping at any other field or blank between them, so a heading two blank rows up is used
but a label of the field above is not.

**Test cases:**
- Unit: heading 45 pt above a lone line is its label; with another blank between them it is not.
- Corpus: D2 f13 and f16 labelled "… Signature", f15 and f18 "Print Name".

### F4 — "No label found" never reaches review (medium)

**Seen in:** D2 f13, f15, f16, f18 (`issues: ["no label found"]` in `01-reading.json`).

**Cause:** `form_fields.issues` is computed for every field, but `derive` uses `issues` only for the `not_asked`
list. A field the AI fails to answer falls back to its id as label (`derive.py:316`) with no word about why.

**Proposed fix:** an asked field's issues that matter to a person ("no label found", "holds a sample value to
replace", a box outside the page) go into its `needs_review` text, unless the AI's answer resolved it (a label given
for a field with none counts as resolved; a sample value still needs a look).

**Test cases:** unit: an unanswered field with no label is flagged "no label found"; an answered one with a label from
the AI is not flagged; a sample value stays flagged.

### F5 — Left labels pile up across a row of fields (medium)

**Seen in:** D5 f5–f7 ("Year · Make/Manufacturer · Body Type · Model" for the Model box); D4 f2 ("`Section 1:
Vehicle Information": a heading and a stray character); D1 f8 ("Typed or Printed Name: · Date:" for the date line).

**Cause:** `PageText.left` takes every line of the "label cell" to the left whose middle lies within the field's
height, which in a row of boxes includes the captions of the boxes before it. Captions above boxes (form layouts) are
read as left labels.

**Proposed fix:** a left label ends at the nearest field or blank to its left on the same row (the captions belong to
those); when the field has a caption directly above, that wins over the left text. Strip leading punctuation that is
not part of a word.

**Test cases:**
- Unit: four boxes in a row each captioned above get their own caption; "Name: ____ Date: ____" gives "Date:" to the
  second blank.
- Corpus: D5's Model box labelled "Model", D1 f8 "Date:".

### F6 — The dropped-name flag is not shown (low)

**Cause:** `derive.Flags.name_dropped` is stored in `version_reviews.flags`, but the fields endpoint's `Flags`
(`routes.py:64`) and review's `FLAG_WARNINGS` (`review/checks.py:34`) do not include it, so nobody learns that the AI's
name or description was refused.

**Proposed fix:** add it to the endpoint and a review notice ("The suggested name or description was not used"); it is
not a warning before approval (it concerns the document, not its fields).

**Test cases:** API: a run whose description is too long returns `flags.name_dropped = true`; the panel shows the
notice.

### F7 — Text addressed to an AI is only looked for in the page text (low)

**Cause:** `ADDRESSED_TO_AI` searches `reading.layout` (`derive.py:442`); field names, tooltips, values, option words
and the uploader's instructions reach the AI through `<fields>` and `<uploader_instructions>` but are not searched.
A document whose only injected text is in a tooltip is therefore not flagged (not yet shown by a test).

**Proposed fix:** search every untrusted string that goes into the message (the same set `untrusted.clean` is applied
to), not only the layout.

**Test cases:** unit: an injection only in a tooltip raises `addressed_to_ai`; only in the instructions raises it.

### F8 — Documentation and configuration drift (low)

- `05-detection.md` §3.2–3.3 still describe a `<write_name_and_description>` tag and a nullable `document` key; the
  code asks for a name and description on every version (`schema.py:225`, `prompt.py:107`).
- `tests/README.md` says `03-request.json` holds the model and the JSON schema; it holds only `system` and `user`.
  Either the file gains the model, effort and schema (it should, to rebuild a run) or the README is corrected.
- `.env` sets `AI_REASONING_EFFORT=medium`; ADR-DET4 chose `low`. Decide which is the default and record it.

### F10 — An extra field is placed on its anchor words, not on the blank (high)

**Seen in:** D7 run: `party_1.full_name` at `[72.0, 665.9, 110.7, 679.1]` and `party_1.title` at
`[72.0, 679.7, 108.7, 692.9]`, exactly the words "NAME:" and "TITLE:"; the value would be drawn over the label.

**Cause:** `derive._anchor` returns the box of the first `search_for(anchor_text)` hit and uses it as the field's
place. The anchor says where to look, not where to write. It also takes the first hit on the page, so with two
"NAME:" on page 14 the left one won only by order.

**Proposed fix:** the place is the free space after the anchor on its row (from the anchor's right edge to the next
word, field or column gap, at least ~60 pt), or under it when the row is full; among several hits, the one nearest the
fields of the same party (or ask the AI for the occurrence number). Still flagged "check its position".

**Test cases:**
- Unit: anchor "NAME:" with free space to its right gives a box starting after the colon, same row; two "NAME:" on a
  page, the field of the left column's party lands in the left column.
- Corpus: D7 printed name and title boxes start right of their labels.

### F11 — A non-shared value repeated in many places becomes many values (medium)

**Seen in:** D7 run: the kind of entity and the address, each asked 9 times in identical sentences, became 9 keys each
(`party_1.address` … `party_1.address_9`), so the signer would be asked for the address 9 times.

**Cause:** only `signature`, `initials`, `date_signed` and `party_name` are shared (`review/values.py` `SHARED`, §4.3);
"other repeats stay separate because they can differ". That holds for two different addresses (a notice address and a
billing address), not for the same blank in the same sentence repeated.

**Proposed fix:** let the AI say which fields are one value (a `same_as` id on a field, or value groups like
`checkbox_groups`), checked by our code (same party, same `holds`), and merged into one key with many places, as
shared values are. The fixed `SHARED` list stays as the default when the AI says nothing.

**Test cases:**
- Unit: two address blanks marked one value merge into one key with two places; marked one value across two parties
  is refused and kept separate with a note.
- Corpus: D7 gives one address and one kind of entity, 9 places each.

### F9 — The test corpus lacks the shapes found here, and has no pass mark (high)

Every document in the corpus before this testing typed its blanks as underscores, so the reader's narrowest rule
passed every test. The rules F1 adds read how a page looks, so they are only as good as the documents they are
measured on; the corpus must hold the documents that would fool them, and a change must meet a stated mark.

**Proposed:**

1. **Flat twins**: a tool in `tests/detection/` that removes every form field and keeps the printed page, so a
   fillable document gives a flat twin whose places are known from its fields (D3f, D4f, D6f).
2. **Trap documents, generated** (so they can be committed: no third-party text), built by a script beside
   `build_extended_nda.py`, one for each way a drawn line is not a blank: underlined headings and defined terms,
   links, a ruled table, a form-style table, header and footer rules on every page, a full-width separator, a line
   under typed underscores, a line under a form field; and one for each way it is: underlined spaces (regular,
   no-break, zero-width), an underline over a label and the spaces after it, signature and date lines under headings,
   lines in two columns.
3. **The local corpus** gains D1–D7 and the twins, each with an expected answer drafted by `score.py --draft` and
   confirmed by the owner.
4. **Pass marks**, checked with `score.py` before the fixes are merged:

   | Measure (`score.py`) | Mark |
   |---|---|
   | `extra` on the trap documents that hold no blank | 0 |
   | `found` on the trap documents that hold blanks, D3f, D4f, D7 | every marked place (unmarked ones are topic 8) |
   | `found` and `extra` on the documents scored before | unchanged |
   | the other measures (`holds`, `filled by`, `required`, `shared`, `roles`) on the documents scored before | no drop beyond the run-to-run variance two clean runs show |

   The reader's half (places found, places wrongly added) is deterministic and is also asserted in the API's unit
   tests on the generated documents; the AI's half is measured by the corpus.

---

## Fix plan

Ordered by dependency: F9's corpus and pass marks come first, so every later change is measured against them; F5 and
F3 change how labels are read, which F1's new blanks reuse; F2 sizes both underscore and drawn blanks. The fixes are
merged only when F9's marks are met (task 13).

## Task tracker

| # | Task | Status | Evidence of completion |
|---|---|---|---|
| 1 | Record findings and test cases | done | this document |
| 2 | F9: flattening tool, generated trap documents, D1–D7 and twins in the corpus, drafted expected answers, pass marks in `score.py` | todo | — |
| 3 | F5: left labels end at the neighbouring field; caption above wins | todo | — |
| 4 | F3: label above for lone lines reaches the heading | todo | — |
| 5 | F1: drawn lines and thin bars as blanks | todo | — |
| 6 | F2: signature and initials boxes grow into the space above the line | todo | — |
| 7 | F4: field issues reach `needs_review` | todo | — |
| 8 | F6: `name_dropped` shown | todo | — |
| 9 | F7: addressed-to-AI search covers every untrusted string | todo | — |
| 10 | F8: design doc §3.2–3.3, tests README, effort default | todo | — |
| 11 | F10: extra fields placed in the space after their anchor | todo | — |
| 12 | F11: the AI marks repeated fields that are one value; merged by key | todo | — |
| 13 | Re-run the corpus (D1–D7, twins, traps), meet F9's pass marks, update `tests/outputs/SCORES.md` | todo | — |
