# Search, sort and "needs approval" (design tweaks)

## 1. Problem

Three lists grow without a way to find one item in them: a department's templates (sorted by name, no search), its
envelopes (newest first, no search) and To countersign (a plain "contains" search). A template waiting for approval
is visible only by opening the Templates tab and reading each card's state.

## 2. Functional requirements

| # | Requirement |
|---|---|
| S1 | One search, on the server, for templates, envelopes and To countersign: forgiving of typos (trigram matching), case-insensitive, an exact part of a word always found. |
| S2 | Templates are searched by the template's name. Envelopes and To countersign by the document's name, the envelope's title, and each signer's name or email. |
| S3 | While searching, the best match comes first; ties newest first. Paging stays stable ("Show more" never repeats or skips). |
| S4 | Templates are newest first by default, with a sort menu: Newest, Recently updated, Oldest, Name (A–Z). While searching the menu shows Best match. |
| S5 | A department with a template waiting for approval shows a dot on its Templates tab and on its card on the Departments page, with the number in words for screen readers. |
| S6 | Searching never changes what the rest of the page counts: the Templates tab's number and the send dialogs' templates are the whole department's. |

## 3. Non-functional requirements

- **Speed**: a search answers in under 200 ms for 100 000 envelopes in a department; trigram GIN indexes on every
  searched column, so a match is an index lookup, not a scan.
- **Safety**: the query is a bound parameter, its `%` and `_` are letters; at most 100 characters.
- **Accessibility**: the search box is labelled; results and their count are announced politely; the dot has a text
  alternative.

## 4. Business logic

- **Normalising** (`kernel.search.normalize`): trimmed, inner spaces collapsed, at most 100 characters; empty means no
  search.
- **A match**: the text contains the query (`ILIKE '%q%'`), or the query is close to some run of words in it
  (`q <% text`, pg_trgm's word similarity at or above 0.5, set per transaction: typos score about 0.6
  and above, unrelated short words under 0.3). One or two characters have no
  trigrams, so they match by containing only.
- **The score** of a text: 1 when it contains the query, else its word similarity; an item's score is the best of its
  texts (for an envelope, across its signers too).
- **Order**: score descending, then the list's own date descending, then id; the cursor carries all three.

## 5. Architecture decision (ADR S-1)

**Context.** Three modules (documents, envelopes, signing) list things to search; each wrote its own matching, and
To countersign's was a plain `ILIKE`.

**Decision.** The matching rule lives once in the kernel (`kernel/search.py`): normalising, the match and score SQL
for given columns, the threshold, and the cursor's encoding. Modules pass their columns (constants of their own) and
keep their own queries. PostgreSQL's `pg_trgm` does the work; no search service.

**Consequences.** One rule, one threshold, one test of what matches. A module adds search by naming its columns and an
index. A search engine (OpenSearch, Typesense) would be a separate service for a need a GIN index meets at this size.

## 6. Data design (migration 0028)

- `CREATE EXTENSION IF NOT EXISTS pg_trgm`.
- GIN `gin_trgm_ops` indexes: `documents(name)`, `envelopes(title)`, `envelope_recipients(name)`,
  `envelope_recipients(email)`.

## 7. Complexity

- Without a search: unchanged (one index range, O(log N + k) for a page of k).
- With a search: the matching rows m come from bitmap index scans, O(m) to score, O(m log m) to order; a page is
  then O(k). m is the number of matches, not the list's size; ordering by score cannot be served by an index.

## 8. Interfaces

- `GET /api/v1/departments/{d}/documents?q=&sort=newest|updated|oldest|name` (q present: best match first).
- `GET /api/v1/departments/{d}/envelopes?q=&status=&cursor=`
- `GET /api/v1/me/countersign?q=&state=&cursor=`
- Department summary `counts.to_approve`: templates whose newest version is waiting for approval (not archived),
  through a provider documents registers, as envelopes does for the send counts.

## 9. Test strategy

- Kernel: normalising; the SQL a column list makes.
- API, against Postgres: a typo finds the template; an exact part of an email finds the envelope; best match first;
  paging through matches never repeats; `%` is a letter; the department's `to_approve`.
- Web: the templates toolbar (search, sort, Best match while searching), the envelopes search, the dot on the tab
  and the card.

## Task tracker

| # | Task | Status | Evidence |
|---|---|---|---|
| 1 | Kernel search, migration 0028 | done | `kernel/search.py`; `0028_search.py`; `tests/kernel/test_search.py` |
| 2 | Templates: search and sort; `to_approve` | done | `documents.service.list_documents`, `count_to_approve`; `departments/approvals.py`; `tests/modules/documents/test_search.py` |
| 3 | Envelopes and To countersign search | done | `envelopes/store.SEARCH_SQL`; `signing/inbox.py`; `test_list.py`, `test_countersign.py` |
| 4 | Web: toolbar, envelopes search, dots | done | `ListControls`, `Select` `labelHidden`, `useDebounced` (shared); `DocumentsSection`, `EnvelopesList`; `Tabs`/`StatCard` `attention`; documents, envelopes, departments tests |
| 5 | Full check, deploy, PR | done | `make check`; PR #23 |

### Decisions while building

- **A sort chosen while searching applies**: with none chosen, a search orders by best match; choosing Newest, Name
  or another orders the matches that way. The menu shows Best match only while searching.
- **The customer is the signer**: copies and countersigners are the firm's own people, not who an envelope is for.
- **To countersign keeps its own order among equal matches**: soonest expiry first while waiting, newest first once
  countersigned (`search.beyond` / `search.order`, `soonest_first`).
