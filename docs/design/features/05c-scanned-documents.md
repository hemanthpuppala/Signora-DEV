# Phase 5c — Scanned documents (LLD)

Parent: [`05-detection.md`](05-detection.md) · Follows [`05b-detection-findings.md`](05b-detection-findings.md) ·
Branch: `phase-5c/scanned-documents`

## Problem

A scanned agreement is a picture of each page: no text layer, so no words to search, no underscores to read. Today
processing stops such a version at `needs_ocr` ("Scanned pages can't be read yet"). The owner's constraint: no local
OCR model; the AI does the reading.

## What was measured first

Two 2-page NDAs with known answers, rendered to image-only PDFs, sent to the AI as page images (the same reading
rules, places answered with boxes in 0–1000 page coordinates):

| | Basic NDA | Unilateral NDA |
|---|---|---|
| places found, parties, signing order | 11 of 11, right | 18 of 18, right |
| boxes on the right line (ends within a few points, foot within 4 pt) | 11 of 11 | **9 of 18** |
| cost | $0.0012, 16 s | $0.0017, 22 s |

The AI reads a scan very well; its **coordinates** are not exact where blanks are stacked (six lines 14 pt apart:
boxes one line off). A value written one line off is wrong. So the AI must not be the source of positions where the
page itself gives them.

## Design: lines from the image, meaning from the AI (numbered marks)

1. **Find the lines on each image page, in code** (`detection/scan_lines.py`, no model): render the page, find the
   dark horizontal strokes (an underline, a signature line), keep the stretches with no ink on the text row above
   them (the F1 rule, on pixels), drop strokes across most of the page's ink width (a rule) and strokes whose ends
   meet a vertical stroke (a table's or a box's border). Each becomes a blank with an exact position (`scanned`).
2. **Show the AI the page with numbered marks**: each blank's id (`f7`) is drawn as a small tag at the start of its
   line on the page image, and the image is sent with the usual message. The AI answers per id, as for any field, so
   it never gives coordinates for these places.
3. **Places with no line** ("Name:" and space) are the AI's extra fields, as on text pages; on an image page it gives
   their box (`ExtraField.box`, 0–1000), placed from it and flagged "placed from the image: check its position".
4. Everything after (checks, keys, F2's room to sign, F11, review, sending, signing) is unchanged.

**Processing**: a version with pages without text goes to detection like any other (`needs_ocr` is no longer set).
Versions already at `needs_ocr` move to `detecting` with their detection queued (migration), as Phase 5 did for
`processed`.

## As built, and what testing changed

`scan_lines.py` reads a page's lines from its pixels: an adaptive ink threshold (the page's paper grey less 45, so a
blurred line still counts), the page **straightened first** (the angle within ±3° at which the ink's rows line up
most sharply, the projection-profile estimate; lines found on the straight page, their boxes turned back), long thin
strokes with gaps of up to 2 pixels bridged (a horizontal closing), a stroke kept only with **paper under it** (past
its own 1 pt edge) and nothing written on the text row above, rules and borders dropped, each blank with its free
height above (`headroom`, for F2). `scan_images.py` draws each field's id on its page's picture; `ask` sends the
pictures after the text; `derive` places a scanned page's extra fields from their box and grows a scanned signature
by its measured headroom (a scan has no words to stop it).

Testing on realistic scans changed the first version three times:
- **Turned pages** (a scanner feeds paper at an angle): a 0.5° turn already gave 2 of 11 and wrong fragments, since a
  turned line spans pixel rows and looked too thick. Fixed by straightening the page first.
- **Blur and low resolution**: a blurred line is grey, lighter than a fixed threshold: 0 of 11. Fixed by judging ink
  against the page's own paper. That let the top edge of bold, blurred text through (+13 wrong fields), fixed by
  requiring paper under a line; that in turn refused real lines on straightened pages (their rough edge sits right
  under them), fixed by looking past the line's own 1 pt edge.
- **Two blanks of a row a point apart** (a turned page) were merged into one box running backwards: blanks are now
  merged row by row, left to right, only where they touch (the class of review finding #2 in Phase 5b).

**Line detection on realistic scans** (both NDAs; turned 0 to ±2.5°, blur, JPEG 40 to 60, 100 to 200 dpi; 8 variants):
every line found within 6 pt in all 16 runs, no wrong field; within 4 pt except where a comma follows the line on the
picture ("______,") and widens it by up to 6 pt. 85 to 165 ms a page.

**End to end with the AI** (the product's pipeline):

| Document | Places | Same meaning as the text version | Calls | Cost |
|---|---|---|---|---|
| Basic NDA, clean scan | 11 of 11 | 11 of 11 | 1, no problems | $0.0015 |
| Unilateral NDA, clean scan | 18 of 18 | 18 of 18 | 1, no problems | $0.0021 |
| Basic NDA, turned 1°, blurred, JPEG 60, 100 dpi | 11 of 11 | 11 of 11 | 1, no problems | $0.0014 |
| Unilateral NDA, the same | 18 of 18 | 18 of 18 | 1, no problems | $0.0020 |
| UL Lafayette NDA, 14 pages, turned −0.8°, blurred, JPEG 70 | 31 lines of 31, plus its two unmarked places from the AI's box (flagged) | its 9 repeated values each one field (F11) | 1, no problems | $0.0048, 52 s |

A text document with the new prompt (the Unilateral NDA) answers as on `main`: 18 of 18, one call.

## Requirements

| # | Requirement |
|---|---|
| FR-S1 | A version with image pages is detected, not stopped. |
| FR-S2 | On an image page, every drawn line with nothing written on it becomes a field at its exact position; rules and table borders do not. |
| FR-S3 | The AI receives each image page with its fields' ids drawn on it, and answers per id. |
| FR-S4 | A place on an image page with no line is placed from the AI's box and flagged for a look. |
| FR-S5 | Text pages of the same document are read as before (a mixed document works). |
| NFR-S1 | Line positions within 2 pt of the truth on the test scans; no wrong fields from text, rules or borders. |
| NFR-S2 | Reading an image page: O(W·H) pixels once at 150 dpi (about 0.1 s a page). |

## Decisions

- **ADR-S1: positions from pixels, meaning from the AI (numbered marks).** Measured: AI coordinates are one line off
  on stacked blanks (9 of 18); a stroke's pixels are exact. No OCR engine (owner constraint).
- **ADR-S2: `numpy` is declared** as the API's dependency (it was only indirect): the image arithmetic is array work.
- **Limits, recorded:** text addressed to an AI cannot be looked for on an image page (no text); labels come from the
  AI only; strongly skewed or handwritten scans are not handled specially.

## Task tracker

| # | Task | Status | Evidence |
|---|---|---|---|
| 1 | Design and measurement | done | this document |
| 2 | `scan_lines.py`: lines from image pages | done | `scan_lines.py`; `test_scanned.py`; realistic scans (above) |
| 3 | Read stage: image pages give `scanned` blanks | done | `read.py`, `reading.scanned_pages`, `Placement.headroom` |
| 4 | AI message: marked page images; `ExtraField.box` | done | `scan_images.py`, `run.ask`, `prompt`, `schema.ExtraField.box` |
| 5 | Derive: extra fields on image pages placed from their box | done | `derive._scanned_box`, `_room_to_sign` by headroom |
| 6 | Processing: no `needs_ocr`; migration for existing versions | done | `processing.py`; migration 0027 and its data test |
| 7 | Tests: unit, real AI on the scans, full gate | done | 20 tests in `test_scanned.py`; real AI runs (above); full gate |
