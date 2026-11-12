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
| FR2 | A website is accepted as people type it (`scoutboard.com`, `https://www.scoutboard.com/team`) and kept as its domain (`scoutboard.com`). Anything that is not a public host name is a field error and creates nothing. |
| FR3 | After sign-up, the company's logo is looked up by its domain and kept by Signora. |
| FR4 | The header shows the logo after the divider when there is one; otherwise the company's name, as today. |
| FR5 | The logo is served only to the company's signed-in members. |
| FR6 | A logo found for a website the company has since changed is not kept. |

## 3. Non-functional requirements

| # | Requirement | Threshold |
|---|---|---|
| NFR1 | Sign-up never waits for or depends on the logo service. | No logo.dev call in the request path. |
| NFR2 | The logo service being down, slow, out of credits or without a key never breaks a page. | Every failure ends in "show the name". |
| NFR3 | The secret key never reaches a browser. | Server-side only; the browser loads the logo from our API. |
| NFR4 | Hostile input cannot make the server fetch anything but logo.dev. | Only `api.logo.dev` and `https://*.logo.dev` download links; no redirects followed. |
| NFR5 | Only a small PNG is kept. | PNG signature checked; at most 512 KB, read no further. |
| NFR6 | A page view costs nothing extra. | The logo is in `/me` already loaded; the image is cached `immutable` under a hash-versioned URL. |

## 4. Business rules

- The website is optional. Blank means none.
- Accepted: `http`/`https` or no scheme; a host name of at least two labels with an alphabetic (or
  IDN) top-level label. Refused: IP addresses, `localhost` and other single labels, credentials,
  other schemes, ports out of range. `www.` is dropped; IDNs are kept in ASCII (`xn--…`).
- The look-up is a background job queued in the sign-up transaction: it runs only if the sign-up
  commits.
- logo.dev answers:
  - 200: download the logo as a PNG sized for a dark header (`format=png`, `size=128`,
    `theme=dark`) and keep it with its `etag`.
  - 202 (still indexing), 429, 5xx, or the service can't be reached: try again with the job's
    backoff (30 s doubling, 7 tries, about half an hour in all).
  - 404 (no brand or no logo): done. The company shows its name.
  - 400/401/402/403 (our key or account): logged, done. Retrying cannot fix it.
- Without `LOGO_DEV_SECRET_KEY` the job does nothing; the name shows.
- The logo is stored only while the workspace's website is still the domain it was found for.

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
  - `company_logo.py`: `request_logo` (enqueue), `find_and_keep` (the job), `logo_of` (serving).
- **Frontend**: `shared/ui/AppShell.tsx` `TopBar` shows `WorkspaceMark`: the logo, falling back to the
  name if the image fails to load.

## 6. Data

Migration `0029_company_logo` adds to `workspaces`:

| Column | Type | Rule |
|---|---|---|
| `website` | text, null | the domain; 4-253 characters |
| `logo_sha256` | text, null | the blob in the workspace's store |
| `logo_bytes` | integer, null | set together with `logo_sha256` |
| `logo_etag` | text, null | logo.dev's version of the logo, for a later refresh |

Check `logo_complete`: `logo_sha256` and `logo_bytes` are set together, and only with a website.
The migration first runs the deferred `created_by` check that migration 0003's system-workspace row
leaves pending (all migrations run in one transaction), then defers the constraint again.

## 7. Complexity

Everything is O(1) per sign-up and per page view: one indexed row read, and one job with two HTTP
requests. The download is read in chunks and stops at 512 KB.

## 8. Interfaces

- `POST /api/v1/auth/signup/complete`: adds `website?: string | null`. A bad website is a 422 with
  field `website`.
- `GET /api/v1/me`, `PATCH /api/v1/workspace`: `workspace.logo_url: string | null`
  (`/api/v1/workspace/logo?v=<sha256 prefix>`).
- `GET /api/v1/workspace/logo`: `image/png` for a member; 404 without a logo; 401 signed out.
- Env: `LOGO_DEV_SECRET_KEY` (optional).

## 9. Tests

`apps/api/tests/modules/identity_access/test_company_logo.py`: website rules (accepted and refused
forms); logo.dev answers 200, 404, 400-403, 202, 429, 5xx and unreachable; download links off
logo.dev, over http or to an IP never fetched; non-PNG, oversize, gone and redirecting downloads
not kept; sign-up keeps the domain and queues one look-up; blank website queues nothing; a bad
website creates nothing; a found logo served to members only with `immutable` caching; no logo
means the name; a changed website discards the late logo; no key means no call.
Web: `shared/ui/WorkspaceMark.test.tsx` for the header mark (logo, name, fallback when the image fails).

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
| 10 | Live check with a real key | todo | needs `LOGO_DEV_SECRET_KEY`; the migration must follow 0028 first (§6) |
