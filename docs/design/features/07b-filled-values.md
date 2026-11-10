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
| 4 | Text sizes: measured at approval (0020), backfill command | done | `typesetting/sizes.py` (`text_sizes`: words' sizes by row, binary search per place, half points, the page's median when the row is empty, 72 at most); `review/text_sizes.py` (`measure` at approval, from the working copy, one insert; `measure_unmeasured`, optionally one company); documents' `VersionForReview` carries its working copy; `signora measure-text-sizes [--workspace]`. A place on a page without words (a scan) stays unmeasured and uses the fallback. Tests: `test_sizes.py` (a generated PDF: 11 pt row, 9.2 → 9, page median, missing page), `test_text_sizes.py` (approval measures; the command measures once), `test_send_form.py` (the fixture's date box: 10 pt) |
| 5 | The fit rule on the server: send refuses a value too long; the form carries sizes and the rule's numbers | done | `typesetting/fit.py` (`place_size`, `fitted_size`, `baseline`); only width refuses: a short box's own size may be under 6 pt, and a value that fits at it is drawn at it (found by the 200-value send test); `envelopes/sending.py` `fits` (every place of the field; ticks always fit): "Too long for its box". A recipient's email in an Email box is not refused: it is theirs, drawn at the smallest size and clipped. Tests: `test_sending.py` (a year after a printed "20": "26" fits, "2026" refused), `test_typesetting.py` |
| 6 | Web: the overlay draws with the font, on the line, fitted; the Details step warns while typing | done | `features/envelopes/typeset.ts` (loads the envelope's font once with `FontFace`, which `font-src 'self'` allows without a stylesheet; measures with a canvas in that font; the server's rule with the server's numbers; `fitsEverywhere`); `ValuesOverlay.tsx` as SVG text: baseline on the line, the size from the place, squeezed into the box only for a recipient's email wider than the box at 6 pt; ticks centred. Details: "Too long for its box" while typing, Next held. Tests: `send.test.tsx` (the warning and Next, with a stubbed measure: the test DOM has no canvas) |
| 7 | Checks, deploy, PR into `phase-7/envelopes` | done | PR #10 into `phase-7/envelopes`; deployed on the tailnet; the approved NDA measured (every box 12 pt) |
| 8 | The envelope page laid out like the document page: the document with what is filled in (and signed, once anyone signs) on the left; the recipients with their actions (send again, copy link, edit), each set apart, on the right; the timeline below (owner request, 2026-11-09) | done | Two shared pieces of the design system, one definition each (owner: "yes that is the correct approach"): `ViewerLayout`/`ViewerPane`/`DetailsPane` (the pinned viewer beside its details, from `document.module.css`; the document page and review use it) and `ItemList`/`Item`/`ItemHead`/`ItemActions`/`ItemAction` (a hairline panel of rows, actions on their own line under a rule; versions and recipients use it; on `/dev/ui`). `EnvelopePage`: the document with its values on the left, recipients and the envelope's settings on the right, the timeline below; the route is full width. Checked in headless Chromium (the gallery's recipients list). Tests: `envelopes.test.tsx`, `document.test.tsx`, `review.test.tsx` |

## Sources

- DocuSign Community, fields cannot move text: <https://community.docusign.com/esignature-111/is-it-possible-to-have-fields-move-text-depending-on-their-size-after-filling-597>
- DocuSign Community, fixed width and formatting: <https://community.docusign.com/sending-8/is-there-a-way-to-make-text-box-fields-expand-as-you-type-591>
- DocuSign Community, prefilled fields keep their width: <https://community.docusign.com/developer-tools-175/gaps-in-the-envelope-template-when-filling-via-api-26262>
- DocuSign Community, the name follows the adopted signature unless locked: <https://community.docusign.com/esignature-111/why-do-some-signers-have-their-names-automatically-change-after-signing-their-contract-480>
- DocuSign developer blog, signers updating their data: <https://www.docusign.com/blog/developers/dsdev-enabling-signers-to-update-their-data>

### Owner review of the envelope page (2026-11-09)

| # | Change | Evidence |
|---|---|---|
| 8.1 | The timeline moved into the right panel. Below both panels it made the layout one screen tall, so the pinned viewer scrolled away with it, and the PDF (which keeps its own scroll while pinned) seemed stuck | headless Chromium: the viewer's top 397 px before and 189 px after scrolling the page 700 px (pinned under the bar) |
| 8.2 | Recipients as cards in groups (Signers, Countersigners, Receives a copy): initials, status, party and email, their moments (sent, read, signed, days left), and Remind, Copy link, the email's edit; Send again only for an email not delivered. `ItemList cards` with `Item leading/actions` (one definition) | `envelopes.test.tsx`; screenshot |
| 8.3 | Remind one person: `POST /envelopes/{e}/recipients/{r}/remind` (`Idempotency-Key`; 409 once signed or before their turn); the timeline names them | `test_follow.py` |
| 8.4 | Settings as label and value: `FactList` in the design system | `envelopes.test.tsx` |
| 8.5 | Tooltips take no room while hidden (`display: none`, fading in with `@starting-style`): a hidden tip at the right edge had widened the page by 4 px | headless Chromium: page width equals the window; a hovered tip shows |
| 8.6 | Recipients' groups and the timeline open and close (`Disclosure`, a native `<details>` with a chevron and a count) and scroll inside themselves: two cards show, the third's edge peeking (`ItemList visible`); the timeline at 340 px. Cards made compact (32 px initials, tighter rows and foot) | headless Chromium: four signers show 304 of 505 px; the page as wide as the window; the viewer pinned; `components.test.tsx` (Disclosure) |

### Code review of the pull request (2026-11-09)

| # | Change | Evidence |
|---|---|---|
| 9.1 | Tooltips sit in the browser's top layer (a manual popover placed by `Tooltip`: centred over what it names, kept inside the window, under it when there is no room above; hidden by a scroll). The details column became a scroll area in 8.x, which clipped the tips of the icon-only actions, their only visible names. `shared/lib/topLayer` is the one test for the top layer, used by `Tooltip` and `Select` | headless Chromium at 1280 px: the action bar's tip and a right-edge row's tip are in the top layer, wholly inside the window, and the column gains no sideways scroll; `components.test.tsx` (IconButton) |
| 9.2 | A screen's `ActionBar` is the first child of `ViewerLayout`, not of the details. From laptop width it heads the right column above what scrolls; on phones it comes before the document and stays under the top bar for the whole page, so Save and Undo are never below the PDF. The layout is one grid, one screen tall, in place of two panes pinned separately | headless Chromium: at 1280 px the bar sits over the details (704 px in all); at 390 px, scrolled 900 px, the bar's top is at 64 px, under the top bar |
| 9.3 | A field chosen on the PDF or from "Things to check" opens a closed Fields section before bringing it into view: `Section` takes `open` and `onOpenChange` for a screen that must open it itself | headless Chromium (closed, then reopened by the screen); `components.test.tsx` (Section, opened by its screen) |
| 9.4 | The preview's width is the sum of each character's width (ADR: as `typesetting.fit` sums glyph advances and the PDF draws them), measured a character at a time and kept per font, O(len(text)); the browser's kerning and ligatures no longer narrow it, and the drawn text has neither. Rejected: turning kerning off on the canvas, which not every browser supports | pymupdf: `text_length("AV")` equals the sum of "A" and "V"; `typeset.test.ts` (a value's width) |
| 9.5 | The Details step asks for the envelope's font as soon as the form is in and judges "Too long for its box" only once it has arrived (before, a stand-in font was measured). Until then nothing is called too long; Send still checks | `send.test.tsx` (too long for its box) |
| 9.6 | A typed value is previewed and measured as the server keeps it: a year typed in two digits is the whole year (`typeset.kept`). A day of 0 or a year of one or three digits is refused at its box when the box is left, in the server's words, and holds Next (`FieldInput.refused`) | `typeset.test.ts`, `FieldInput.test.tsx` |
| 9.7 | The envelope page's document pane says "Loading the document…" while its form loads, and why with "Try again" when it cannot be had; it showed a count of values in both cases | `envelopes.test.tsx` |
| 9.8 | The scroll rule leaves Cmd+wheel alone as it does Ctrl+wheel: the PDF viewer zooms on either, and the page scrolled as it zoomed on macOS | `scrollLatch.test.ts` |
| 9.9 | `Select`: the highlighted option is kept in view (the list alone is moved); on a touch screen the search box is 16 px and takes the focus only when tapped, so opening a list neither zooms the page nor raises the keyboard over it; the list is placed in what the keyboard leaves visible | headless Chromium: 30 options, the last chosen, in view on opening and after Home, twelve ArrowDown and End; at 390 px with touch the focus stays on the trigger and the box is 16 px |

Open, for the owner: the envelope page draws its document from the send form, which is for sending: it refuses an archived document and an archived department. An envelope sent before its document or department was archived therefore shows 9.7's message instead of the document. (Access is not the cause: seeing sends and sending are always held together, by the Editor role or a department grant.) Showing it needs the envelope's own read of its pages, places and fit rule (a contract change).
