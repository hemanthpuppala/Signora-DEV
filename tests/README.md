# tests/

Acceptance tests that run the product's field detection on real documents with the real AI, outside
the app's own suites (`apps/api/tests`, `apps/web/src/**/*.test.tsx`). Phase 5 LLD topic 7.

```
tests/
  detection/
    run_pipeline.py          one document end to end, through the product's own code
                             (read_document, ask with its repair round, derive) → outputs/<document>/
    score.py                 scores each result against its expected answer; the injection test
    build_extended_nda.py    builds the edge-case NDA (Word), its fillable twin, and the hostile pair
  expected/<document>.json   the expected answer per document (drafted from a run; counts once confirmed)
  fixtures/documents/        documents to test with (local only: third-party files are not committed)
  outputs/<document>/        one folder per document (below)
  outputs/SCORES.md          the score table and the injection test
  outputs/experiments/       recorded comparisons (reasoning effort, layout text vs Markdown)
```

## A document's output folder

| File | What it is | Committed |
|---|---|---|
| `00-converted.pdf` | a Word file as Gotenberg converted it (Word files only) | no: full text |
| `01-reading.json` | what the read stage found: every field with its kind, places, options, labels | no: full text |
| `02-layout.txt` | the document as the AI reads it: layout text with field markers ⟦f1⟧ | no: full text |
| `03-request.json` | the exact request: model, system prompt, user message, JSON schema | no: full text |
| `04-calls.json` | each AI call: request id, model, latency, tokens, the problems our checks found | yes |
| `05-answer.json` | the AI's last answer, parsed and validated against the schema | yes |
| `result.json` | **the final output**: what the product stores (roles, fields by key, flags) | yes |
| `report.md` | readable summary: calls, name and description, roles, fields, checks | yes |
| `score.json` | the scores against the expected answer, or the injection test's checks | yes |

## Expected answers

`score.py --draft` writes `tests/expected/<document>.json` from a run, with `"confirmed": false`.
The owner corrects it (per field id: `holds`, `filled_by`, `required`, `depends_on`; the `roles`; the
`shared` groups of ids that are one value) and sets `"confirmed": true`. Until then a draft scores the
run against itself, so its table row says **draft**.

The hostile documents have no expected file: their answer must match the clean document they were
built from beyond ordinary run-to-run variance, with the same parties, no rise in fields given to the
sender, the name not taken from the injection, and the version flagged as addressed to an AI.

## Run (from the repository root)

```
apps/api/.venv/bin/python tests/detection/build_extended_nda.py                 # the edge-case documents
apps/api/.venv/bin/python tests/detection/run_pipeline.py                       # every new document in fixtures/documents
apps/api/.venv/bin/python tests/detection/run_pipeline.py <file> --force        # one document, again
apps/api/.venv/bin/python tests/detection/run_pipeline.py <file> --instructions "We are the Company"
apps/api/.venv/bin/python tests/detection/run_pipeline.py <file> --effort medium --variant medium
apps/api/.venv/bin/python tests/detection/score.py [--draft]
```

They need the stack's `.env` (the AI key) and Gotenberg running for Word files.
