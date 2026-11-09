# Phase 7b — Filled values on the page (LLD)

Parent design: [`../signora-platform.md`](../signora-platform.md) · Previous: [`07-envelopes.md`](07-envelopes.md) ·
Branch: `phase-7b/filled-values` (from `phase-7/envelopes`, merged into it before `main`).

## Problem

What is typed into a document's blanks should look like part of the document. Today a value is drawn in the
system font, sized from its box's height only, centred in the box, and nothing keeps a long value inside it
("2026" spilled out of "20__"). Names were also fixed at send from what the sender typed, so a signer could not
correct their own printed name. This phase sets one rule for drawing a value, used by the preview now and by the
signed PDF in Phase 8, and fills a signer's name fields the way DocuSign does.

## Owner decisions (2026-11-09)

1. Follow DocuSign's practice, not the owner's guesses: "do not get biased by my question — I need DocuSign
   standards".
2. The document's own text never moves. A blank longer than its value keeps its empty line, as in DocuSign (a field
   cannot push the text around it).
3. Fonts live in the backend, several can be listed, one is the default. The owner will give a font later; it is
   added to the list and made the default then.
4. A value sits on its line, at the size of the agreement's text around it, and never leaves its box.
5. A signer's name fields are filled at signing from the name they sign as (DocuSign's Full Name, First Name and
   Last Name fields), not fixed at send.
6. Not changed: a State field takes any text (the "N?A" was a test of the flow).

## What DocuSign does (sources at the end)

- A field is a fixed box on the page; the document is never reflowed. Prefilled text fields keep their width.
- The sender sets a field's font and size; the signer cannot change formatting.
- Full Name, First Name and Last Name fields show the name the signer adopts at signing. The signer can change it on
  the Adopt Your Signature step, and the name fields follow, unless the account locks the recipient's name.
- The Email field shows the recipient's email.

## Functional requirements

| # | Requirement |
|---|---|
| FR-1 | The backend keeps a list of fonts (id, family name, file, licence) and a default. A font's file is served at `GET /api/v1/fonts/{id}` to anyone (the signer has no session), cached as immutable. |
| FR-2 | An envelope records the font it was sent with; its preview and its signed PDF (Phase 8) use that font even if the default later changes. |
| FR-3 | When a version is approved, each text place gets the size of the agreement's text on its row (the median size of the words on the same row, else of the page); a version approved before this keeps the fallback (FR-5). |
| FR-4 | A value is drawn left-aligned, its baseline resting just above the box's bottom edge (the line), at the place's text size. |
| FR-5 | Without a measured size the size is the box's height × 0.72, capped at 11 pt. |
| FR-6 | A value too wide for its box at that size is drawn smaller to fit, down to 6 pt; wider still, it is refused ("Too long for its box"), by the server on send and while typing in the send form. A value shown in several places must fit in each. |
| FR-7 | A signer's Full name, First name and Last name fields are not asked of the sender and not stored at send: at signing (Phase 8) they show the name the signer signs as, which the signer may change from the name the sender gave. Email fields keep showing the recipient's email from the send. A Legal name (it may be a company's) stays the sender's to fill. |
| FR-8 | Before signing, the preview and the envelope page show a name field as the signer's name to come, in a quieter style ("at signing"), never as a value. |

## Non-functional requirements

| # | Requirement |
|---|---|
| NFR-1 | Preview and signed PDF agree: the same font file, the same sizes and fit rule from one definition on the server. |
| NFR-2 | Measuring text sizes at approval adds under 300 ms for a 20-page PDF; the send form gains no PDF read. |
| NFR-3 | Fonts are open-licence files kept in the repository with their licence; no font is fetched at run time. |
| NFR-4 | The font endpoint sends `Cache-Control: public, max-age=31536000, immutable`; the id names one file forever (a new file gets a new id). |

## Business logic

- **The fit rule** (one definition, `typesetting.fit`): `size = min(place_size, width / advance(text, 1 pt))`; if
  `size < 6` the value does not fit. The server is the authority; the web repeats only the measuring, with the
  numbers the server gives (place size, minimum), to warn while typing.
- **The line**: the baseline sits `max(1.5, 0.18 × size)` points above the box's bottom edge. Detected blanks are
  drawn on the underline, so the box's bottom is the line.
- **Text size of a place**: the words on the same row as the place (vertical centres within 4 pt, the detection
  rule); their median size, rounded to 0.5 pt. None on the row: the page's median word size. Checkboxes, choices and
  signatures have no text size.
- **Names at signing**: a party's `full_name`, `first_name`, `last_name` fields become "given at signing", like a
  signature: not in the send form, not stored by the send. The sender's name for the signer is the proposal the
  signer sees when adopting a signature (Phase 8).

## Architecture decisions

- **ADR-7b.1 A `typesetting` module, pure, owns fonts and the fit rule.** Envelopes (preview data, send check) and
  Phase 8 (writing the PDF) depend on it; it depends on nothing but the font files and PyMuPDF's font metrics.
  Rejected: the rule in the web only (the signed PDF would differ), or in envelopes (Phase 8 would reach into it).
- **ADR-7b.2 Text sizes in their own table, written at approval.** `placement_text_sizes(placement_id, size)` is
  derived from the PDF and the approved places. Approved places are frozen by triggers; a separate table leaves them
  untouched and lets a command backfill versions approved earlier. Rejected: computing on every send-form read
  (opens the PDF each time), a column on `field_placements` (frozen once approved).
- **ADR-7b.3 The envelope pins its font** (`envelopes.font`), as it pins its version: what was sent is what is
  signed.
- **ADR-7b.4 Liberation Sans is the default until the owner's font arrives.** Open licence (SIL OFL 1.1) and the same
  widths as Arial, the most common font in agreements, so a value reads as part of the page.

## Data design (migration `0020_filled_values`)

```sql
CREATE TABLE placement_text_sizes (
  placement_id uuid PRIMARY KEY REFERENCES field_placements(id) ON DELETE CASCADE,
  workspace_id uuid NOT NULL,
  size real NOT NULL CHECK (size > 0 AND size <= 72)
);
ALTER TABLE envelopes ADD COLUMN font text NOT NULL DEFAULT 'liberation-sans';
```

Envelopes keep `font` among the columns their trigger keeps as sent. Existing envelopes take the default.

## Algorithms and complexity

- Text sizes at approval: one pass over each page's words (PyMuPDF `get_text("dict")`), rows found with the
  detection `RowIndex` (sorted by centre, binary search): O(W log W + P log W) per page for W words and P places.
- Fit: measuring a value is O(n) in its characters; a send checks every value in every place, O(total characters).

## Interface contracts

- `GET /api/v1/fonts/{font_id}` → the font file (`font/ttf`), 404 for an unknown id.
- The send form and the envelope view gain `font: {id, family, url}`; each place gains `text_size: number | null`
  and the form gains `fit: {min_size: 6, fallback_ratio: 0.72, fallback_cap: 11, baseline_ratio: 0.18}`.
- The send form's fields no longer include a signer's name fields; `FormField` gains nothing for them.
- Send refuses a value that does not fit: `422 validation-failed`, `fields.{id}`: "Too long for its box".
- `signora.modules.typesetting`: `FONTS`, `DEFAULT_FONT`, `font_file(id) -> Path`, `fit(text, width, size, font)
  -> float | None`, `text_sizes(pdf, places) -> dict[placement_id, float]`.

## Test strategy

- Unit: the fit rule (fits, shrinks, refuses; several places), text sizes from a generated PDF with known sizes,
  the font list (every file exists, has a licence, ids unique).
- API: the font endpoint (headers, 404); approval writes sizes; the backfill command; send refuses a value too long;
  a send stores no name values and still stores emails; the envelope pins its font.
- Web: the overlay draws with the font at the given size on the line and shrinks a long value; a name field shows
  "at signing"; the Details step warns "Too long for its box" while typing; Details no longer lists name fields.
- Headless Chromium: the review step's preview against a screenshot check.

## Task tracker

| # | Task | Status | Evidence |
|---|---|---|---|
| 1 | This design | done | this file |
| 2 | Names at signing: out of the send form and the send's prefill; preview and envelope page show "at signing" | done | `envelopes/form.py` (`from_recipient` on each field: "name" or "email" for a party's own details; the signers' field-id lists dropped), `sending.py` (only emails prefilled, for signers and countersigners; a sender's value for such a field refused: "Filled in from the signer"), `store.py` (prefill rows for every party's recipient); web: Details hides them, signers no longer proposed from Details, the preview draws the email and the name to come (quieter, italic), the envelope page too. Tests: `test_sending.py`, `test_send_form.py`, `test_send.py` (the fixture gains a client printed name and email), `send.test.tsx` |
| 3 | `typesetting`: font list, default font file and licence, the font endpoint; envelopes pin a font (0020) | done | `modules/typesetting` (`fonts.py`: the list, Liberation Sans with its OFL licence, widths read once; `routes.py`: `GET /api/v1/fonts/{id}`, public, immutable cache, 404 unknown; `views.py`: the font and the fit rule's numbers for screens); `0020_filled_values` (`envelopes.font`, kept as sent by the trigger; `placement_text_sizes` keyed to the version, not to each place: a cascade from places made the 2000-field save test's second save take 1.0 s, at its limit; a draft's saves never touch the table now, 6 of 6 under the limit); the send form and the envelope view carry the font, each place its `text_size`. Tests: `test_typesetting.py` (5), `test_schema.py` |
| 4 | Text sizes: measured at approval (0020), backfill command | todo | — |
| 5 | The fit rule on the server: send refuses a value too long; the form carries sizes and the rule's numbers | done | `typesetting/fit.py` (`place_size`, `fitted_size`, `baseline`); only width refuses: a short box's own size may be under 6 pt, and a value that fits at it is drawn at it (found by the 200-value send test); `envelopes/sending.py` `fits` (every place of the field; ticks always fit): "Too long for its box". A recipient's email in an Email box is not refused: it is theirs, drawn at the smallest size and clipped. Tests: `test_sending.py` (a year after a printed "20": "26" fits, "2026" refused), `test_typesetting.py` |
| 6 | Web: the overlay draws with the font, on the line, fitted; the Details step warns while typing | todo | — |
| 7 | Checks, deploy, PR into `phase-7/envelopes` | todo | — |
| 8 | The envelope page laid out like the document page: the document with what is filled in (and signed, once anyone signs) on the left; the recipients with their actions (send again, copy link, edit), each set apart, on the right; the timeline below (owner request, 2026-11-09) | todo | — |

## Sources

- DocuSign Community, fields cannot move text: <https://community.docusign.com/esignature-111/is-it-possible-to-have-fields-move-text-depending-on-their-size-after-filling-597>
- DocuSign Community, fixed width and formatting: <https://community.docusign.com/sending-8/is-there-a-way-to-make-text-box-fields-expand-as-you-type-591>
- DocuSign Community, prefilled fields keep their width: <https://community.docusign.com/developer-tools-175/gaps-in-the-envelope-template-when-filling-via-api-26262>
- DocuSign Community, the name follows the adopted signature unless locked: <https://community.docusign.com/esignature-111/why-do-some-signers-have-their-names-automatically-change-after-signing-their-contract-480>
- DocuSign developer blog, signers updating their data: <https://www.docusign.com/blog/developers/dsdev-enabling-signers-to-update-their-data>
