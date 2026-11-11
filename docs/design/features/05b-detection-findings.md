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

**Fix (built):** `detection/drawn_lines.py`, a fourth kind of mark beside underscores, placeholders and checkbox
glyphs, called from `blanks.find_blanks`; each blank it gives carries `drawn` (`reading.FoundField`).

1. **Candidates**: from `page.get_drawings()`, stroked horizontal segments, rectangles and quads at most 2 pt tall
   (`THICKNESS_MAX`). **Pieces of one line are joined first** (on one row, at most 1.5 pt apart, `JOIN_GAP`) and the
   line is judged whole: a table's row rule is often drawn once per column, and each half alone looks like a short
   empty line (seen on the fillable Mutual NDA, where 8 row rules came back as blanks before the join). At least
   20 pt long (`LENGTH_MIN`).
2. **Only the empty stretches, character by character**: the visible characters on the text row above the line (12 pt,
   `TEXT_ABOVE`), from `rawdict`, through a `RowIndex`. A character is empty when it draws nothing (spaces, zero-width
   characters, soft hyphens: `writing_space.visible`, the one definition F2 and F10 use). **By character, not by
   word**: a word processor's underlined gap followed by a comma is one "word" ("␣␣␣␣␣,") whose box spans the line;
   judged by word, D7's gaps were refused (seen while testing). The line is cut where visible characters sit and each
   remaining stretch of at least 20 pt is a blank, so one underline under "Name:␣␣␣␣␣" gives the stretch after the
   label and an underlined word gives nothing.
3. **Not a blank**:
   - wider than 80 % of the text's width (`FULL_WIDTH`): a separator or a table's row rule;
   - an end meets a vertical line (`TOUCH`, 2 pt): a table's or a box's border;
   - **in the top or bottom tenth of the page (`MARGIN`) with no label printed to its left on its row**
     (`LABEL_REACH`, 72 pt): a header or footer rule. This replaces "at the same place on every page", which missed
     a rule on one page (TC-843's line under its title) and would have refused what should be kept: "Initials: ____"
     in every page's footer;
   - under a form field or a blank already found in the text (more than half its length overlapped).
4. **Merged and sized** as underscore runs are: stretches on one row closer than 6 pt are one blank; the box is the
   line with the text row above it (F2 then grows signatures and initials).
5. **Labels and layout** by the same `PageText` code as other blanks; the layout text shows `⟦fN⟧` where the spaces
   were.
6. **Backstop**: a drawn blank the AI answers as filled by **nobody** is not kept as a field, with a note in the
   proposal (`derive`): a drawn line is the least certain mark, and the AI has read it in its sentence. A typed blank
   keeps its treatment.

Cost: one pass over a page's drawings (sorted to join pieces) and one over its characters, then a row index:
O(D log D + C) a page. Nothing after the read stage changes. A version read before the fix is detected again from the
document page (Find fields again, §1.3) while it is not approved.

**Edge cases and how each is treated:**

| Case | Treatment |
|---|---|
| an underline over a label and the spaces after it | the empty stretch after the label only (step 2) |
| underlined words: headings, links, defined terms | not a blank: visible words above |
| a line under typed underscores | not doubled (step 3) |
| header and footer rules, section separators | not a blank (step 3) |
| initials or a signature line in a footer, with its label | a blank (step 3: labelled) |
| ruled tables, a table's row rules drawn per column | not a blank (steps 1 and 3) |
| captioned boxes: a ruled cell with a small caption (PRINT NAME, CITY on a government form) | not found: the cell's lines are borders; a different shape, recorded under topic 8 |
| dotted or dashed lines (`........`, `- - -`) | not covered: dot leaders in contents tables would be false blanks; left to topic 8 |
| boxes drawn as rectangles (a drawn `□`, comb boxes) | not covered: a separate mark, recorded for later |
| lines inside an image, scanned pages | not covered: scans are blocked as needing OCR (Phase 4) |
| white or hidden text above a line | accepted risk |

**Backstops for a wrong candidate:** the AI reads every marker in its sentence; a drawn-line blank the AI says
**nobody fills** is not kept (step 6); every result is reviewed and approved by a person before it can be sent.

**Tests (`tests/modules/detection/test_drawn_lines.py`, 13):** underlined spaces after a label (found, labelled by
it); a thin filled bar (found); no-break spaces on the line (found); one underline under a label and its spaces (the
stretch after the label); an underlined word (none); a line under typed underscores (not found twice); a separator,
whole and drawn in two pieces (none); a ruled table (none); an unlabelled footer rule (none) and footer initials
(found); a line under a form field (none); a turned page (placed as shown); a drawn line the AI says nobody fills (not
kept) and one a party fills (kept). The 9 that expect a blank fail on the reader before F1; the 4 that expect none
guard against finding too much.

**On every real document** (read stage, before → after):

| Document | Before | After | |
|---|---|---|---|
| D7 UL Lafayette NDA | 0 (`none`) | **31**, all drawn | every line on the page |
| D1 Basic NDA, D2 Unilateral NDA, the Financial NDA | 11, 18, 11 | 11, 18, 11 | underlined words and the line under typed signatures refused |
| Mutual NDA (fillable) | 22 | 22 | its table's row rules, drawn per column, refused |
| D3f REG 135, D4f TC-843 (flat) | 6, 6 | 6, 6 | no wrong field from their table borders or title rule; their places are captioned boxes (topic 8) |
| D6f contractor agreement (flat), the other fillable forms | unchanged | unchanged | |

**D7 through the product's own pipeline** (`run_pipeline.py`, F1, F2 and F10 together; one AI call, 26.4 s, 16,493
tokens in of which 16,490 cached, 3,240 out, no problems): the other party signs, UL Lafayette countersigns; the name
"UL Lafayette Non-Disclosure Agreement" and a correct description; the party's name in 9 places; signatures 36 pt
tall; the printed name and title placed after their labels in the other party's column; UL Lafayette's printed name
and title not asked. Left: the entity type and address asked 9 times each (F11), and the role label "Ul Lafayette"
(a label built from the slug capitalises each word; an acronym loses its capitals).

### F2 — Signature boxes on flat documents are one text line tall (high)

**Seen in:** D1 (12.3 pt), D2 (13.4 pt), the Word trade-secret NDA (12.3 pt). Fillable documents for comparison:
Mutual NDA 28.8 pt, trade-secret NDA form 23.9 pt.

**Cause:** a blank's box is the bounding box of its underscore text (`blanks._runs`); nothing changes it once the AI
says it holds `signature` or `initials`. `SignatureMark` scales a mark to its box's height: a typed signature is drawn
at 0.7 × height (≈ 9 pt, smaller than the 11 pt body text) and a drawn one is squeezed into a 13 pt strip, though the
page leaves 30–40 pt of free space above each signature line.

**Fix (built):** `detection/writing_space.py`, applied in `derive` where `holds` is first known. A `blank` place
holding `signature` or `initials` grows upward into the free space above its line, keeping the line as its bottom
edge so the mark sits on it, as a pen signature does:

- **Height**: up to 36 pt (`SIGN_HEIGHT`). Automatic field detection in e-signature tools places a signature field on
  the line it finds, and default signature fields are drawn about 28–50 pt tall; 36 pt sits in that range and is about
  three lines of 11 pt text.
- **Never over anything**: it stops 2 pt (`CLEARANCE`) below the nearest visible word or other field above it that
  overlaps it horizontally. Words made only of spaces, zero-width characters or soft hyphens draw nothing and do not
  stop it. Space is measured against every field's original place, so one grown box never limits another.
- **A form field's box is never changed**, whatever its height: signing fills that form field, and its author drew
  it (it is `signature`, `text` or another kind, not `blank`).
- **Only on a page whose text reads upright as shown.** "Above the line" follows the text, not the page: on a page
  whose text is shown sideways (`/Rotate` turning upright text), the box is kept as read rather than guessed.
- **Cost**: per page holding such a line, one pass over its words and places into a `RowIndex`, then each line looks
  only at the rows above it: O(W + P) per page, O(k) per line.

**Tests (`tests/modules/detection/test_writing_space.py`, 7):** a line with free space above grows to 36 pt and keeps
its bottom; a heading above stops it 2 pt below; a signature line above stops it at that line; initials grow and a
printed name keeps its size; a form field's short signature box is unchanged; a page whose text is shown sideways keeps
the box; spaces and invisible characters leave the space free. The four growth tests fail without the change.

**On the real documents** (re-derived from their saved answers, no new AI call): D1's two signatures 12.3 → 25.0 pt
(stopped below "DISCLOSING PARTY" and "RECEIVING PARTY"), D2's two 13.4 → 36.0 pt; bottoms unchanged, every other
field identical.

**Not changed:** the boxes a person draws or resizes in review keep their size; a version detected before this change
keeps its boxes until its fields are found again (Find fields again, §1.3, while not approved).

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

**Cause:** two parts.
1. **The contract was ambiguous.** The schema asked for "the exact words around the blank", which says nothing about
   where the blank is relative to them (before, after, between); no placing rule can be exact from that.
2. **The words were used as the place.** `derive._anchor` returned the box of the first `search_for` hit: the anchor
   says where to look, not where to write. Taking the first hit, with two "NAME:" on page 14, the left one won only
   by order.

**Fix (built):**
1. **Contract**: `anchor_text` is now "the words printed immediately before the blank, on the same line: its label"
   (`schema.ExtraField`); the blank is the empty space right after them. The limit is one constant, `ANCHOR_MAX` (80),
   used in the description and in the search.
2. **One model of free space** (`writing_space.py`, shared with F2): `PageSpace` holds a page's visible words and its
   fields' places; F2 asks it for the room above a line, F10 for the room after a label:
   - **something printed after the label on its row** (a value such as "Dr. Carolyn Bruder", the rest of a sentence,
     another column): the blank can only be between them, from 3 pt after the label (`LABEL_GAP`) to 2 pt before
     that text (`CLEARANCE`); with less than 60 pt there (`MIN_WIDTH`, room for a date at 10 pt), there is no blank.
     Printed text after a label means its value is given, never that the blank moved;
   - **nothing after it (the label ends its line)**: the rest of the line up to the text's right edge (the furthest
     word, or the left margin mirrored on a page of short labels); when that is under 60 pt, the line below, from the
     label's left edge, when it is free;
   - one text line tall; invisible words (spaces, zero-width characters) leave the space free.
3. **Which printing of the words: the party's own, or none.** The printing is chosen first, the one closest to the
   same party's found fields on the page (`_party_places`, from the answer); the blank is the room after that printing
   or nothing. The room after another printing is never taken instead: in a signature block printed in two columns,
   it belongs to the other party. With none of the party's fields on the page, the first printing in reading order
   with room. The place is then taken, so a second field cannot land on it.
4. **No room**: `check` reports it to the repair round with the same choice of printing ("there is no free space after
   'NAME:' on page 14 where the other fields of ul_lafayette are: give the words printed right before the blank, and
   check who fills it (a value already printed is not a blank)"); if it remains, the field is dropped with a note
   rather than written over the text or into another party's column.
5. The review note reads "placed after the words printed before it: check its position".

Order in `derive`: found fields, then extra fields are placed (taking their space), then signatures and initials grow
(F2), so a signature the AI found after "By:" is placed after its label and then given room to sign.

**Tests:** in `test_writing_space.py`: after its label on its row, starting `LABEL_GAP` after it, at least
`MIN_WIDTH` wide; of two printings of "NAME:" in a two-column signature block, each party's lands in its own column
and the left one stops before the right column; a label ending its line at the right edge puts the blank on the line
below; a value printed after the label is never skipped for the line below; no room is a problem for the repair
round, then dropped with a note; an extra signature after "By:" is placed and then grows; **a field the AI wrongly
gives to a column whose value is already printed, listed first, is a problem for the repair round and is dropped,
and the other party keeps its own column** (on the pushed `dd0e7c6` it took the left column and pushed the real field
out; the test fails there). On D7 the same wrong fields for UL Lafayette's printed name and title are refused and the
other party's name and title keep their place. `test_derive`'s extra
field test now asserts the place starts after its words (it was the words before).

**On D7** (the drawn-line experiment, now with this code and a new AI call: 16,493 tokens in, 2,790 out, 23.8 s, no
problems): the AI gave "NAME:" and "TITLE:"; the name is placed at `[113.7, 665.9, 322.0, 679.1]` and the title at
`[111.7, 679.7, 322.0, 692.9]`: after their labels, in the left column, stopping before the right column's "NAME:".

**For Phase 8 (signing):** a typed signature is drawn at 0.7 × its box's height without fitting its width
(`SignatureMark`); with F2's taller boxes a long name in a narrow box runs past it. Typed marks should take the
smaller of that size and the size that fits the box's width, as drawn marks already do.

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
   | `found` on the trap documents that hold blanks and D7 | every marked place (unmarked ones are topic 8) |
   | `extra` on D3f and D4f (ruled government forms) | 0: their places are captioned boxes, counted under topic 8 |
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
| 5 | F1: drawn lines and thin bars as blanks | done | `detection/drawn_lines.py`; 13 tests in `test_drawn_lines.py` (9 fail before it); every real document recounted; D7 through the real pipeline (F1 above) |
| 6 | F2: signature and initials boxes grow into the space above the line | done | `detection/writing_space.py`; 7 tests in `test_writing_space.py` (4 fail without it); D1 and D2 re-derived (F2 above) |
| 7 | F4: field issues reach `needs_review` | todo | — |
| 8 | F6: `name_dropped` shown | todo | — |
| 9 | F7: addressed-to-AI search covers every untrusted string | todo | — |
| 10 | F8: design doc §3.2–3.3, tests README, effort default | todo | — |
| 11 | F10: extra fields placed in the space after their anchor | done | `schema.ExtraField.anchor_text` contract; `writing_space.PageSpace.room_after`, `DocumentSpace.place_after`; 5 tests in `test_writing_space.py`, `test_derive` updated; D7 rerun (F10 above) |
| 12 | F11: the AI marks repeated fields that are one value; merged by key | todo | — |
| 13 | Re-run the corpus (D1–D7, twins, traps), meet F9's pass marks, update `tests/outputs/SCORES.md` | todo | — |
