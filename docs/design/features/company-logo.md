# Company logo

## 1. Problem

The console header shows the Signora mark, a divider and the company's name in capitals. A company
wants to see its own logo there. At sign-up we already ask for the company's name; we add its
website (optional), find the company's logo from it, and show the logo after the divider. Without a
website, or when no logo can be found, the header stays exactly as it is today.

## 2. Functional requirements

| # | Requirement |
|---|---|
| FR1 | The sign-up form (after the email is verified) has an optional "Company website" field. |
| FR2 | A website is accepted as people type it (`scoutboard.com`, `https://www.app.scoutboard.com/team`) and kept as its registrable domain (`scoutboard.com`; `shop.acme.co.uk` is `acme.co.uk`). Anything that is not a public host name, or only a public suffix (`co.uk`), is a field error and creates nothing. |
| FR3 | A logo is kept once per domain, shared by every company on it and kept when they are gone. A company on a known domain shows it at once; logo.dev is asked only for a domain not known yet (revised 2026-11-11). |
| FR4 | The header shows the logo after the divider when there is one; otherwise the company's name, as today. |
| FR5 | The logo is served only to the company's signed-in members. |
| FR6 | A logo found after the company moved to another website is kept for its domain, not shown by that company. |
| FR7 | The company's owner (its creator) can set, change or remove the website in Settings. A new website drops the old logo and looks up the new one. Nobody else can. |
| FR8 | A domain in use is looked up again: soon after logo.dev could not answer, later when there was none, and monthly to pick up a changed logo (downloaded only if it changed). A domain no company uses is not refreshed; named again, its kept logo shows at once and is refreshed a month on, and "none found" is asked again once that answer is a week old. |
| FR9 | A logo whose file is missing from the store shows the name and is fetched again. |

## 3. Non-functional requirements

| # | Requirement | Threshold |
|---|---|---|
| NFR1 | Sign-up never waits for or depends on the logo service. | No logo.dev call in the request path. |
| NFR2 | The logo service being down, slow, out of credits or without a key never breaks a page. | Every failure ends in "show the name"; a timeout (10 s) skips the look-up, never fails the job. |
| NFR3 | The secret key never reaches a browser. | Server-side only; the browser loads the logo from our API. |
| NFR4 | Hostile input cannot make the server fetch anything but logo.dev. | Only `api.logo.dev` and `https://*.logo.dev` download links; no redirects followed. |
| NFR5 | Only a small PNG is kept. | PNG signature checked; at most 512 KB, read no further. |
| NFR6 | A page view costs nothing extra. | The logo is in `/me` already loaded; the image is cached `immutable` under a hash-versioned URL. |

## 4. Business rules

- The website is optional. Blank means none.
- Accepted: `http`/`https` or no scheme; a host name of at least two labels with an alphabetic (or
  IDN) top-level label. Refused: IP addresses, `localhost` and other single labels, credentials,
  other schemes, ports out of range. `www.` is dropped; IDNs are kept in ASCII (`xn--…`).
- **The key**: the website rule (`domain/website.py`, the one definition) reduces a host to its
  registrable domain with the Public Suffix List shipped with `tldextract` (offline; private
  suffixes included, so `acme.github.io` stays itself). That domain is what logo.dev is asked for
  and what the logo is kept under.
- **One logo per domain** (`company_logos`): its file in the system workspace's store, logo.dev's
  `etag`, the last answer (`checked_at`) and the next look-up (`check_due_at`). A company shows the
  row of its website's domain; deleting or moving a company never deletes it.
- **Naming a domain** (sign-up, Settings; `want_logo`): an unknown domain gets a look-up now; one
  another company is on keeps its schedule; one back in use after being left shows its kept logo at
  once and is refreshed a month on, or is asked again if its "none found" is a week old.
- A sweep (every 15 minutes, only while a key is configured) queues the look-ups due for domains in
  use, and clears the plan of domains nobody uses (they wait until named again).
- The planned time is part of the job's dedupe key: one planned look-up is queued once however
  often the sweep or a request asks, and the next one can always be queued.
- logo.dev answers, and what follows:

  | Answer | Kept | Next look-up |
  |---|---|---|
  | 200, logo unchanged (same `etag`) | nothing downloaded | in 30 days |
  | 200, new logo | downloaded as a PNG for a dark header (`format=png`, `size=128`, `theme=dark`), kept with its `etag` | in 30 days |
  | 202 (logo.dev indexing a domain new to it) | nothing yet; the name stays | after 10 s, 30 s, 90 s (queued to run then, at most 3 in a row); still indexing after them, in 1 hour |
  | 429, 5xx, timeout, unreachable | nothing: skipped, the name stays | in 1 hour |
  | 404, 400-403, an unusable file | nothing | in 7 days |
  | no key (removed after queueing) | nothing; logo.dev not asked | in 1 day |

  None of these fails the job; only our own failures (database, disk) are retried (3 tries).
- Without `LOGO_DEV_SECRET_KEY` nothing is queued; planned look-ups wait until a key is set.
- The website is the owner's alone to change (`PUT /workspace/website`). The answer carries the new
  domain's logo when it is known; otherwise the name shows until it is found.
- A logo whose file is missing: the logo route clears it for its domain (every company on it shows
  its name), plans a look-up for now and answers 404.

## 5. Architecture

- **Server-side look-up through logo.dev's API.** logo.dev's self-hosting rule: a service that keeps
  logos uses the API with a secret key (`GET https://api.logo.dev/v2/brands/logo?domain=…`, Bearer
  `sk_…`). The answer carries a signed download link valid for about a day; we download the file at
  once and keep the file, never the link.
- **Rejected: the browser loading `img.logo.dev` with a publishable key.** Every page view would go to
  a third party and tell it which companies use Signora, with each viewer's IP address; the page
  would depend on that service being up; and logo.dev's terms ask services that store logos to use
  the API.
- **Modules** (identity, which owns workspaces):
  - `domain/website.py`: pure; `company_domain(raw) -> str`, `InvalidWebsiteError`.
  - `logo_dev.py`: the HTTP client, with no database. `find_logo(domain, secret_key, client) ->
    Logo | None`; raises `LogoDevUnavailableError` when trying later may work.
  - `company_logo.py`: `plan_check`, `sweep`, `find_and_keep` (the job), `logo_of` and
    `forget_missing` (serving).
- **Frontend**: `shared/ui/AppShell.tsx` `TopBar` shows `WorkspaceMark`: the logo, falling back to the
  name if the image fails to load.

## 6. Data

Migration `0029_company_logo` added the website and per-workspace logo columns; `0032_company_logos`
(revised 2026-11-11) moves the logo to one row per domain:

`company_logos`

| Column | Type | Rule |
|---|---|---|
| `domain` | text, primary key | the registrable domain; 4-253 characters |
| `logo_sha256`, `logo_bytes` | text, integer, null | the file in the system workspace's store; set together |
| `etag` | text, null | logo.dev's version of the logo; a refresh downloads only when it changed |
| `checked_at` | timestamptz, null | logo.dev's last answer (a logo, or none) |
| `check_due_at` | timestamptz, null | the next look-up; null while no company uses the domain |

`workspaces.website` keeps the registrable domain (`ix_workspaces_website`, partial: a company's
logo and whether a domain is in use are index lookups). Index `ix_company_logos_check_due_at`
(partial): the sweep's scan. The migration reduces existing websites, gives each domain a row with
a look-up due, and drops the workspace's logo columns; the files kept per workspace are not carried
over (each domain is looked up once more).

## 7. Complexity

Everything is O(1) per sign-up and per page view: one indexed row read, and one job with at most
two HTTP requests. The sweep reads at most 200 due rows per run from the partial index,
O(k log n) for k due rows. The download is read in chunks and stops at 512 KB.

## 8. Interfaces

- `POST /api/v1/auth/signup/complete`: adds `website?: string | null`. A bad website is a 422 with
  field `website`.
- `GET /api/v1/me`, `PATCH /api/v1/workspace`: `workspace.website: string | null` and
  `workspace.logo_url: string | null` (`/api/v1/workspace/logo?v=<sha256 prefix>`).
- `PUT /api/v1/workspace/website` `{website: string | null}`: the owner only (403 otherwise);
  422 with field `website` for a bad one. Audited as `workspace.website_changed`.
- `GET /api/v1/workspace/logo`: `image/png` for a member; 404 without a logo or when its file is
  missing (then fetched again); 401 signed out.
- Env: `LOGO_DEV_SECRET_KEY` (optional).

## 9. Tests

`apps/api/tests/modules/identity_access/test_company_logo.py`:
- website rules (accepted and refused forms);
- logo.dev: the request and download; 404 and 400-403 mean none; 202, 429, 5xx, timeouts mean
  not now; download links off logo.dev, over http or to an IP refused; non-PNG, oversize, gone
  and redirecting downloads not kept;
- sign-up keeps the domain and queues one look-up with a key, none without (the sweep queues it
  once there is a key); a blank website plans nothing; a bad one creates nothing;
- the job: a found logo is served to members only, cached `immutable`; each outcome plans the next
  look-up as in §4 and leaves the name; an unchanged logo is not downloaded, a changed one is; a
  changed website discards the late logo; no key asks nothing;
- a missing file shows the name and queues a fetch; the sweep queues each due look-up once;
- Settings: the owner sets, changes and removes the website (old logo dropped, audited); others
  get 403.

Web: `shared/ui/WorkspaceMark.test.tsx` (logo, name, fallback), `SignupCompleteForm.test.tsx`
(website sent, blank sent as null, field error), `account/SettingsPanel.test.tsx` (owner only;
save; remove).

## Task tracker

| # | Task | Status | Evidence |
|---|---|---|---|
| 1 | Website rule (domain) | done | `domain/website.py`; tests above |
| 2 | Migration and model | done | `0029_company_logo.py`; schema test passes |
| 3 | logo.dev client | done | `logo_dev.py`; tests above |
| 4 | Look-up job and storage | done | `company_logo.py`, `jobs.py` |
| 5 | Sign-up field (API) | done | `signup.py`, `schemas.py` |
| 6 | Serve the logo; `logo_url` in `/me` | done | `routes/members.py` |
| 7 | Sign-up form field (web) | done | `SignupCompleteForm.tsx`; `SignupCompleteForm.test.tsx` |
| 8 | Header logo with name fallback (web) | done | `WorkspaceMark.tsx`; `WorkspaceMark.test.tsx` |
| 9 | Full gate | done | API 999 tests, lint, mypy, import contracts; web 374 tests, lint, types, build |
| 10 | Review fixes (PR #24): planned re-checks and sweep, timeouts skip, missing file fetched again, owner's website in Settings, one actor query | done | API 1010 tests, lint, mypy, import contracts; web 377 tests, lint, types, build |
| 11 | Live check with a real key | todo | needs `LOGO_DEV_SECRET_KEY` |
| 13 | A 202 asked again within seconds, three times at most (owner, 2026-11-11): it waited an hour, and a new domain's logo showed only then | done | `INDEXING_BACKOFF`, `LogoDevIndexingError`; `test_company_logo.py` (three retries then hourly; a logo indexed by the retry kept) |
| 12 | One logo per domain, registrable domain as the key (owner, 2026-11-11) | done | `company_logos`, `want_logo`, migration 0032; `test_company_logo.py` (a second company, and one re-created a year later, shown without asking logo.dev; "none" asked again after a week; the sweep leaves unused domains), `test_data_migrations.py` |
