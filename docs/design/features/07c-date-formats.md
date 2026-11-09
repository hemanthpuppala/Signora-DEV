# Phase 7c — Dates as the document writes them (LLD)

Parent design: [`../signora-platform.md`](../signora-platform.md) · Previous: [`07b-filled-values.md`](07b-filled-values.md) ·
Branch: `phase-7b/filled-values`.

## Problem

A date in an agreement is written in many ways: whole in one blank ("Date: ________", "__/__/____"), or split
across blanks ("the ____ day of __________, 20____"). The parts are already their own types (day, month, year), but
nothing records how each blank expects its value written: a year after a printed "20" takes two digits, a month may
be a name or a number, a whole date may be day-first or month-first, short or long. Without it the sender guesses,
types the same date more than once in different shapes, or a value is drawn in a shape the document does not use.

## Functional requirements

| # | Requirement |
|---|---|
| FR-1 | Every field holding a date or a part of one (`date`, `date_signed`, `date_of_birth`, `day`, `month`, `year`) has a format, from a closed list per type (§Business logic). |
| FR-2 | Detection proposes each such field's format from the blank and the text printed around it; a missing or unknown answer takes the type's default. |
| FR-3 | A reviewer sees and changes a field's format; changing a field's type to a date type gives it that type's default; any other type has none. |
| FR-4 | What a sender gives is the value itself, never its writing: a date from a date picker, a day as a number, a month from the twelve, a year in four digits. It is stored in one canonical form. |
| FR-5 | A value is drawn in its field's format, in the preview and in the signed PDF; the "too long for its box" check measures the drawn text. |
| FR-6 | A two-digit year accepted from a sender ("26") is read as 2026: the century of today. |

## Non-functional requirements

| # | Requirement |
|---|---|
| NFR-1 | One definition of the formats and their writing on the server (`review.formats`); the browser repeats only the writing, checked against the same cases (a shared list of examples run by both test suites). |
| NFR-2 | No change to detection's cost: the format is one more key on each field the AI already answers. |
| NFR-3 | Versions approved earlier keep working: their date fields take their type's default format. |

## Business logic

Formats by type (the default first):

| Type | Formats | Example (9 November 2026) |
|---|---|---|
| `date`, `date_signed`, `date_of_birth` | `Month D, YYYY` · `MM/DD/YYYY` · `DD/MM/YYYY` · `MM/DD/YY` · `DD/MM/YY` · `YYYY-MM-DD` · `D Month YYYY` | November 9, 2026 · 11/09/2026 · 09/11/2026 · 11/09/26 · 09/11/26 · 2026-11-09 · 9 November 2026 |
| `day` | `D` · `Dth` | 9 · 9th |
| `month` | `Month` · `MM` | November · 11 |
| `year` | `YYYY` · `YY` | 2026 · 26 |

- The written-out date is the default for a whole date: it cannot be misread day-first or month-first.
- Detection's cues: slashes in the blank or a printed "MM/DD/YYYY" give that order; a printed "20" before a year
  blank gives `YY`; "this ____ day of" gives `Dth` ("the 9th day of"); a month blank before ", 20" gives `Month`.
- Canonical values: a date `YYYY-MM-DD`; a day `1`–`31`; a month `1`–`12` (a name is accepted and kept as its
  number); a year four digits (two digits are read in today's century).
- A format belongs to the field, not the value: the same envelope value drawn in two places of one field is
  written the same way.

## Architecture decisions

- **ADR-7c.1 The format is a property of the field.** A column on `version_fields` (`format`, null for types
  without one), proposed by detection, edited in review, frozen with the version. Rejected: a format per envelope
  (the document's blank decides, not the send) or per place (a field's places are one value).
- **ADR-7c.2 Values are canonical; formats are applied when drawn.** The sender never types a shape, and one
  stored value can be drawn in any format. Rejected: storing the drawn text (it loses the date, so the year
  "26" could not be drawn as "2026" anywhere else, and checks would parse shapes).
- **ADR-7c.3 Writing lives in `review.formats`** with the value checks it already holds (pure, used by sending
  and by signing in Phase 8). The browser's copy is tested against the same examples
  (`packages/contracts/vectors/date-formats.json`), so the two cannot drift silently.

## Data design (migration `0021_date_formats`)

```sql
ALTER TABLE version_fields ADD COLUMN format text;  -- null: the type has no formats
```

Approved versions are frozen by triggers on `version_fields`; the migration only adds a nullable column. Reading a
field of a date type without a format gives its type's default (NFR-3).

## Interface contracts

- Detection's answer: each field (and each extra field) gains `format: one of the formats above | null`.
- `FieldView` and the save body gain `format: string | null`; a save with a format the type does not have is a
  `422` on `fields[i].format`.
- The send form's fields gain `format`.
- `review.formats`: `FORMATS: dict[holds, tuple[format, ...]]`, `default_format(holds)`, `check_value` returns the
  canonical value, `written(holds, value, format) -> str`.

## Algorithms and complexity

Writing a value is O(1) (a fixed number of parts); checking a send stays O(total characters).

## Test strategy

- Unit: every format of every type against the shared examples (Python and TypeScript); canonical values; a
  two-digit year; a month by name.
- Detection: the schema carries `format`; the derive step keeps a valid one and defaults an invalid one; the
  prompt's cues (a live run on the test NDA: the year after "20" proposed as `YY`, the day before "day of" as
  `Dth`, the month as `Month`).
- API: save and read a format; a format of another type refused; a send draws and fits the written value.
- Web: the field editor offers a date type's formats; the send's inputs (a year in four digits, the month from
  the twelve); the preview draws the written value.

## Task tracker

| # | Task | Status | Evidence |
|---|---|---|---|
| 1 | This design | done | this file |
| 2 | Formats and writing in `review.formats`; canonical values; the shared examples | todo | — |
| 3 | `version_fields.format` (0021); review reads, saves and checks it | todo | — |
| 4 | Detection proposes it; a live run on the test NDA | todo | — |
| 5 | Sending: the form carries it; the fit check measures the written text | todo | — |
| 6 | Web: the format in the field editor; the send's inputs; the preview writes values | todo | — |
| 7 | Checks, deploy | todo | — |
