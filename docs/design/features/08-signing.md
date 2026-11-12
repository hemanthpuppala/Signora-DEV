# Phase 8 — Signing and completion (LLD)

Parent design: [`../signora-platform.md`](../signora-platform.md) · Previous: [`07-envelopes.md`](07-envelopes.md) ·
Branch: `phase-8/signing` · Prototype screens: 21–27 (the signer's flow), 17 (countersign), 18 (completed).

## Problem

Phase 7 sends an approved template to its signers, but the link in their email leads nowhere. Phase 8 completes the
envelope's whole life on the happy path: a signer opens their link, proves it is them, agrees to sign electronically,
fills their fields, signs and submits (or declines); when every signer has signed, the countersigners are emailed and
sign the same way; when the last of them signs, the signed PDF is made with a certificate of completion and sent to
everyone. The platform's delivery plan split this into two phases (8, signing; 9, completion); they are one phase here,
so the path a person tests from the first email to the completed copy is whole. Scheduled reminders and expiry stay in
Phase 10.

What Phase 7 already gives this phase: signing links that can be checked (ADR-E1), the recipient's status columns,
one rule for every value (`review.formats`), the typesetting of a value in its box (Phase 7b), and who signs when and
who sees what (Phase 7 §3).

## Topics

| # | Topic | Status |
|---|---|---|
| 1 | Opening the link: a link becomes a session, a clean address, closed links, a countersigner too early | agreed 2026-11-10 |
| 2 | Verifying it is you: the email code, attempts, a new code, how long a session lasts | agreed 2026-11-10 |
| 3 | Consent to electronic records: the disclosure, one tap, what is kept, declining there | agreed 2026-11-10 |
| 4 | The signer's screen: the viewer, their fields, the guide, locked values, earlier signers' submissions, private fields, phones | agreed 2026-11-10 |
| 5 | Signatures and initials: type or draw, adopted once, one tap a place, Apply to all, countersigners' saved signatures, the signing date | agreed 2026-11-10 |
| 6 | Submit: the statement of intent, the server's check, a repeated submit, statuses, the audit record | agreed 2026-11-10 |
| 7 | The countersigners' turn: signed in to Signora, a personal To countersign inbox with a dot, the same signing screen | agreed 2026-11-11 |
| 8 | Decline: final, a reason, everyone stopped, links closed, the sender told, Send again | agreed 2026-11-11 |
| 9 | The done screen (no email until completion) | agreed 2026-11-11 |
| 10 | The signed PDF: the original's pages with values and signatures written in, envelope ID, Signed by frames | agreed 2026-11-11 |
| 11 | The certificate of completion: a separate PDF, each person's events, hashes | agreed 2026-11-11 |
| 12 | Completion: the job, the completed email with both PDFs attached, downloads, failure | agreed 2026-11-11 |
| 13 | Security: limits, headers, logs, isolation, sessions apart, audit | agreed 2026-11-11 |
| 14 | Low-level design: requirements, data, modules, API, tests, tracker | proposed |

---

## 1. Opening the link

### 1.1 Rules

1. **The email's link opens a page; the page exchanges it for a session.** `/s/{token}` is a page with no third-party
   resources. It posts the token to `POST /api/v1/sign/open` and, on success, replaces the address with
   `/sign/{recipient_id}`. The token then stays out of the address bar, the history, bookmarks and any `Referer`.
   The API receives it in a request body, never in a URL, so no access log holds it.
2. **Opening is the person's own press, not a page load.** The page shows "You have a document to review" and one
   button, Review document; pressing it makes the exchange (`POST`). Link-safety services fetch every link in a
   message, and many run the page's script in a headless browser, but none presses a button: a scan opens no
   session, records no "opened" and sends no email code. (Revised in review, R3: an exchange on page load was made by
   scanners that run scripts.)
3. **The link is the same until it closes.** Opening it again, Copy signing link and Send again give the same link
   (Phase 7, ADR-E1). A link closes when the envelope is completed, declined, cancelled or expired, or when that
   person's email is changed (the link version moves on). Several tabs and devices may hold sessions at once.
4. **One browser can hold several people's sessions.** A sender testing both signers in one browser, or a colleague
   who is a countersigner on one envelope and a signer on another, must never act as the wrong person. The cookie
   names a browser session; each person opened in it is a separate grant, and every signer request names its
   recipient in the path (`/api/v1/sign/{recipient_id}/…`), checked against the grants. A tab opened for one person
   keeps acting for that person after another link is opened in the same browser.
5. **"Opened" is recorded once.** The first accepted open sets the recipient's `opened_at` and status `opened`, and the
   envelope's status to `opened` while it is `sent` (statuses only move forward, Phase 7 §1.1). One timeline entry,
   however often the link is opened. "Viewed" is recorded when the document is first shown (topic 4).
6. **A closed link shows one calm page**: "This request is no longer open. Nothing more is needed from you." It
   names nobody (no company, no sender), because the answer must be the same for a link that is not genuine. It never
   says why (completed, cancelled, expired, declined, replaced): the
   link may be in someone else's hands. A token that is not genuine gets the same page, the same response and the
   same status code, so a guess learns nothing.
7. **Someone who has already signed** opens normally (a session, then the email code, topic 2) and lands on their done
   screen (topic 9), not the closed page, until the envelope closes.
8. **Signer links are for signers only.** A countersigner signs in Signora, signed in (§7); a token naming a
   countersigner gets the closed page. Before their turn the countersign page says "It isn't your turn yet. We'll
   email you when the signers have finished."
9. **Expiry is checked whenever a link or session is used**, without waiting for Phase 10's job: past `expires_at`, the
   envelope is closed to signers even while its status still says otherwise. Moving the status to `expired` and its
   emails stay with Phase 10.
10. **Every signer request checks again** that the grant's link version is the recipient's current one, the recipient
    is not revoked, and the envelope is open and not past its expiry. A cancel, a decline, an expiry or a changed email
    therefore ends sessions already open at their next request; the page shows the closed page.

### 1.2 Checks on opening, in order

| # | Check | Fails with |
|---|---|---|
| 1 | The token is genuine (`links.read_token`: one spelling, constant-time HMAC compare) | closed (404 `link-closed`) |
| 2 | The recipient exists, in an envelope that exists | closed |
| 3 | The token's link version is the recipient's, and `revoked_at` is null | closed |
| 4 | The envelope's status is open (`sent`, `opened`, `viewed`, `signed`) and now is before `expires_at` | closed |
| 5 | The recipient is a signer (`kind = 'signer'`; countersigners sign in Signora, §7) | closed |
| 6 | Otherwise: a grant for this recipient in this browser's session (made if absent); `opened` recorded once | 200 |

Checks 2–4 read one row of each table by primary key. The responses for 1–4 are identical in body, status and headers.

### 1.3 Sessions

- **Cookie** `__Host-signora_sign`: a random 256-bit value (`secrets.token_urlsafe(32)`), httpOnly, Secure,
  `SameSite=Strict`, path `/`, no expiry (gone when the browser closes). Only its SHA-256 is stored. It is separate from
  the console's `__Host-signora_session`: being signed in to the console gives no signer access, and the reverse.
- **No CSRF token.** A `SameSite=Strict` cookie is never sent on a request started by another site, and the kernel's
  Origin check (layer 1, Phase 2) refuses a state-changing request from another origin. The signer's page is the only
  caller.
- **Lifetime**: 30 minutes idle (sliding, each request moves it on) and 12 hours at most from creation. When a session
  ends, the page says "Your session ended. Open the link in your email again." Nothing filled in is lost if it was
  saved (topic 4).
- **Cookie missing or expired on `/sign/{recipient_id}`** (a reload after the session ended, the address copied to
  another browser): the same "open the link in your email again" page. The recipient id in that address grants
  nothing on its own.

### 1.4 Data (migration `0025_signing`, owned by a new `signing` module)

```
signing_sessions
  id             uuid pk default uuidv7()
  token_hash     bytea not null unique          -- sha256 of the cookie value
  created_at     timestamptz not null default now()
  last_seen_at   timestamptz not null default now()
  expires_at     timestamptz not null           -- created_at + 12 h

signing_grants                                  -- one per person opened in a browser session
  session_id     uuid not null → signing_sessions on delete cascade
  recipient_id   uuid not null → envelope_recipients
  workspace_id   uuid not null                  -- with recipient_id: the composite key keeps one company
  link_version   int  not null                  -- the version the link carried; must equal the recipient's
  created_at     timestamptz not null default now()
  verified_at    timestamptz                    -- the email code was given (topic 2); null when not asked
  primary key (session_id, recipient_id)
```

Rows past their expiry are refused when read and removed by a periodic job (Phase 10; until then they are harmless).
The opening itself is an audit event on the envelope's chain (`signing.opened`, once per recipient) holding the IP
address and user agent, which the certificate (topic 11) reads.

### 1.5 Interface

| Method and path | Body | Answers |
|---|---|---|
| `POST /api/v1/sign/open` | `{ "token": "…" }` | 200 `{ recipient_id, next }` with the cookie set; 404 `link-closed` |
| `GET /api/v1/sign/{recipient_id}` | — | 200 the signer's state (who, envelope title, sender, `next`); 401 `session-ended`; 404 `link-closed` |

`next` is the first step the person still has: `verify` (topic 2), `consent` (topic 3), `sign` (topic 4) or `done`
(topic 9). The web routes are `/s/[token]` (the exchange) and `/sign/[recipientId]` (the flow); both send
`Referrer-Policy: no-referrer` and `X-Robots-Tag: noindex, nofollow` (topic 13).

### 1.6 Algorithms

Opening is O(1): a token decode, one HMAC, three reads by primary key, an insert of the grant if absent
(`ON CONFLICT DO NOTHING`), and one conditional update
(`UPDATE envelope_recipients SET opened_at = now(), status = 'opened' WHERE id = :r AND opened_at IS NULL`) whose row
count decides whether the audit event and the envelope's move are written. Two opens at the same moment therefore
record one event. A request in the flow is O(1): the cookie's hash looks up the session (unique index), the grant by
its primary key, the recipient and the envelope by theirs.

### 1.7 Edge cases

| Case | Behaviour |
|---|---|
| A mail scanner fetches the link | Loads the page, and may run its script, but presses nothing: no session, nothing recorded, no code sent (1.1.2) |
| The link opened twice, or in two tabs at once | One grant per browser session, one `opened` event (1.6) |
| Two people's links in one browser | Two grants; each tab acts for the person in its path (1.1.4) |
| The person's email is changed while their page is open | The next request fails check 3: closed page. The new link works |
| The envelope is cancelled, declined or expires while a page is open | The next request fails check 4: closed page |
| A token naming a countersigner | The closed page; countersigners sign in Signora (§7) |
| Someone who signed opens their link again | Session, code, then their done screen (1.1.7) |
| A truncated, altered or made-up token | The closed page, exactly as a closed link (1.2) |
| The secret key is rotated | Every outstanding link stops working (Phase 7 ADR-E1); senders use Send again |
| The cookie is blocked (private mode with cookies off) | The open succeeds but the next request has no session: "Allow cookies for this site to sign" |
| The `/sign/{recipient_id}` address is shared | Without that browser's cookie it grants nothing (1.3) |

## 2. Verifying it is you

Applies when the envelope's **Require email code** is on (the default, Phase 7 §4). With it off this step is skipped:
the link reaching the person's inbox is the proof, and the certificate says "Email link".

### 2.1 Rules

1. **A code is sent when the person reaches this step**, unless one is still valid; then the page says "We sent a code
   to m•••@example.com at 8:05 PM" (the time in the envelope's zone, Phase 7 §5). Reloading never floods the inbox.
2. **Six digits, single use, 10 minutes**, from `secrets.randbelow(10**6)`, zero-padded. Only
   `HMAC-SHA256(code_key, recipient_id ‖ link_version ‖ code)` is kept, `code_key` derived from `SECRET_KEY` for this
   purpose alone (as ADR-E1's link key): a copy of the database cannot be tried against the million codes.
3. **Five wrong tries end the code**; a new one is then needed. A new code may be asked for 60 seconds after the last,
   at most five in any hour per person. Only the newest code works. A changed email (the link version moves on) ends
   any code.
4. **The email**: subject "123456 is your code for {template}"; body the code, when it stops working, and "If you
   didn't ask for this, you can ignore it." Category `sign_code`, dedupe key `sign_code:{code id}`, sent through the
   outbox like every email (Phase 2), never with a link in it.
5. **Verification belongs to the browser session's grant** (`signing_grants.verified_at`). A new browser, or a session
   that ended (§1.3), asks for a new code.
6. **The input**: one field drawn as six boxes, `inputmode="numeric"`, `autocomplete="one-time-code"` (phones offer
   the code from the email), a pasted code accepted, checked as soon as the sixth digit is in. A wrong code says
   "That code isn't right. 3 tries left." and clears the field.
7. **Recorded**: `signing.code_sent`, `signing.code_wrong`, `signing.code_locked` (fifth wrong try),
   `signing.verified`, each on the envelope's audit chain with the IP address and user agent. The certificate names
   the method: "Email code to m•••@example.com".
8. **The email is masked** everywhere on the signer's page: the first character of the local part, `•••`, the domain
   (`m•••@example.com`; a one-character local part shows `•••@example.com`).

### 2.2 Data (in `0025_signing`)

```
signing_codes                                   -- at most one live code per recipient
  recipient_id   uuid pk → envelope_recipients
  workspace_id   uuid not null
  link_version   int  not null                  -- a code for an older link version is dead
  code_mac       bytea not null
  sent_at        timestamptz not null
  expires_at     timestamptz not null           -- sent_at + 10 min
  wrong_tries    smallint not null default 0    -- the setting (5) ends the code; checked 0-20, the setting's range
  used_at        timestamptz                    -- set when it verifies; then dead
  window_start   timestamptz not null           -- the hour in which codes are counted
  sent_in_window smallint not null default 1    -- at most 5
```

A new code overwrites the row (upsert), keeping the hour's count. The row's lock is the only lock: a try and a new code
for the same person never interleave.

### 2.3 Interface

| Method and path | Body | Answers |
|---|---|---|
| `POST /api/v1/sign/{r}/code` | — | 200 `{ sent_at, email_masked, resend_after }` (sent, or the live one kept); 429 `code-wait` with `retry_after`; 429 `code-limit` |
| `POST /api/v1/sign/{r}/verify` | `{ "code": "123456" }` | 200 `{ next }`; 422 with the `code` field's message ("That code isn't right. 3 tries left."); 410 `code-ended` (expired, used or locked: ask for a new one) |

`POST …/code` with `{ "again": true }` asks for a new code even while one is live (the 60-second and hourly limits
apply). Both need the session and grant of §1.3.

### 2.4 Algorithm

Verify is O(1): the row by key under `SELECT … FOR UPDATE`, checks (link version, not used, not expired,
`wrong_tries < 5`), one HMAC, `hmac.compare_digest`; on a match `used_at` and the grant's `verified_at` are set in the
same transaction; otherwise `wrong_tries` goes up and the transaction commits (a wrong try is never rolled back).

### 2.5 Edge cases

| Case | Behaviour |
|---|---|
| The code email fails to send | The step says "We couldn't send your code. Try again in a minute."; the email's delivery record shows on the envelope page (Phase 7) |
| An older code entered after a new one was asked for | Wrong (only the newest code's MAC is kept) |
| Two devices at once | Both use the current code; it is single use, so the second device asks for its own |
| The code entered after 10 minutes | `code-ended`: "That code has expired. We've sent a new one." only when the person asks (no automatic send) |
| Five wrong tries | `code-ended`; a new code after the 60-second wait |
| The person's email is changed while they wait for a code | The code is dead (link version) and their next request shows the closed page (§1.1.10) |
| Six codes asked for in an hour | `code-limit`: "Too many codes. Try again after 9:12 PM." |
| The setting is off | No code step; `next` goes from opening to consent |

## 3. Consent to electronic records

### 3.1 Rules

1. **After the code, before the document, once per person.** Consent belongs to the recipient, not the browser
   session: someone who agreed on a phone is not asked again on a laptop.
2. **The disclosure** (the consumer disclosure of the US ESIGN Act, 15 U.S.C. §7001(c)), four short paragraphs:
   - **What this covers**: this agreement from {company}, signed and kept electronically.
   - **A paper copy**: ask {sender's email} at any time; there is no fee.
   - **Withdrawing consent**: choose Decline before signing; it does not affect anything signed earlier. To change
     the email you are reached at, write to {sender's email}.
   - **What you need**: a current browser, this email address, and a way to open a PDF. You can download everything
     you sign.
3. **One checkbox, one button**: "I agree to use electronic records and signatures" and **Continue** (enabled once
   ticked), with a quiet **Decline** beside it (topic 8).
4. **One text, versioned, on the server.** The disclosure is a constant in the `signing` module with a version
   (`esign-disclosure-v1`); the page shows what `GET /api/v1/sign/{r}` returns, filled with the company's name and the
   sender's email. A changed text is a new version; what a person agreed to is never rewritten.
5. **Recorded**: the time, the disclosure version, the IP address and the user agent, as `signing.consented` on the
   envelope's audit chain and on the recipient (3.2). The certificate (topic 11) prints "Agreed to electronic records:
   Nov 10, 2026 at 8:07 PM PST".
6. **Countersigners consent the same way**: they sign electronically too.

### 3.2 Data (in `0025_signing`)

```
signing_consents
  recipient_id        uuid pk → envelope_recipients
  workspace_id        uuid not null
  disclosure_version  text not null
  consented_at        timestamptz not null default now()
  ip                  inet                      -- unknown when no valid address reached the server
  user_agent          text                      -- at most 512 characters, cut beyond
```

Insert only (a trigger refuses UPDATE and DELETE): consent, once given, is a fact.

### 3.3 Interface

| Method and path | Body | Answers |
|---|---|---|
| `POST /api/v1/sign/{r}/consent` | `{ "disclosure_version": "esign-disclosure-v1" }` | 200 `{ next }`; 409 `disclosure-changed` with the current text when the version sent is not the current one; 403 `verify-first` when the code is required and not yet given |

Repeat-safe: `INSERT … ON CONFLICT (recipient_id) DO NOTHING`; a second consent answers 200 and records nothing more.
O(1).

### 3.4 Edge cases

| Case | Behaviour |
|---|---|
| Consent given, then the person leaves | Next time `next` is `sign`: straight to the document |
| Consent given on one device, the link opened on another | Code (that browser), then the document; no second consent |
| The page was open while the disclosure's version changed | `disclosure-changed`: the new text is shown to agree to |
| The version changes after consent, before submit | What they agreed to stands; the version recorded is the one shown |
| Decline from the consent screen | Withdrawing consent before signing: a decline (topic 8) |
| Consent attempted before the code | `verify-first`; the page goes back to the code |

## 4. The signer's screen

### 4.1 Layout

The console's PDF viewer (the shared `ViewerPane`), with no side column. A slim bar pinned at the top holds the
template's name, how many of the person's required fields are left ("3 fields left") and the **guide button**
(4.3). After the last page comes the Submit block (topic 6): the statement, the checkbox and **Sign and submit**, at
the end of the document, not pinned over it. **Finish later** (topic 8) is in the bar's menu.

### 4.2 What is on the page

| A field | Shown as |
|---|---|
| The person's own, still to fill | A soft highlight; required ones marked |
| The person's own, filled | Their value in the envelope's font, editable until they submit |
| Given by the sender | Drawn in place, locked |
| Submitted by an earlier signer | Drawn in place, read-only: signatures, initials, names, dates and every other value that is not private |
| Private and someone else's (tax number, bank account, date of birth, Other marked private) | An empty box marked "Private" |
| Another signer's, not yet submitted | A faint empty box named by their party ("Client 2") |
| A countersigner's | A faint empty box, "{Company} signs here", until completion |

**The server decides what is sent**: other people's private values and countersigners' values never reach the
signer's browser; hiding them on screen is not the protection.

**Only one person's fields are ever highlighted or guided**: the person whose link opened the page. Signers sign in
any order (Phase 7 §3), so each signer's page guides their own party's fields (Client 1's link guides Client 1's
fields, Client 2's guides Client 2's), whoever has or has not signed. A countersigner's page guides the countersigner's
fields.

### 4.3 The guide

One button in the top bar leads the person through their required fields, then to the Submit block:

| State | The button says | Clicking it |
|---|---|---|
| Nothing filled yet | **Start** | Moves to the first required empty field and points at it |
| A field is being pointed at, or some are left | **Next** | Moves to the next required empty field and points at it |
| Every required field is filled | **Complete** | Moves to the Submit block and points at the checkbox |
| The checkbox is ticked | (hidden) | Sign and submit, at the end, is enabled |

- **The pointer**: a curved arrow drawn in beside the field, with a label "Fill {field label}" ("Sign here" for a
  signature, "Initial here" for initials), and a soft ring around the box. It sits in the top layer, follows the
  field when the page scrolls or zooms, and never covers the box. It draws in once (about 400 ms); with reduced motion
  it simply appears. At the Submit block the same arrow points at the checkbox: "Tick to confirm".
- **When the field is filled**, the pointer leaves and the button reads **Next** (or **Complete** after the last one).
  Clicking the field itself is the same as being pointed at it.
- **Order**: reading order, by page, then top to bottom, then left to right (a place's top edge, ties by its left
  edge). A field with places on several pages is visited at its first place. Optional fields are not guided; they
  are filled by clicking them. A signing date is never guided (filled at submit, topic 5).
- **The counter** counts the person's required fields that are asked (4.5) and still empty, and is announced to
  screen readers ("2 fields left").

### 4.4 Filling a field

- **On a computer**: the field is typed into in place, in the envelope's font at the size the signed PDF will use,
  centred as it will be printed (Phase 7b: `fit.place_size`, `ALIGN center`), so what is seen is what is signed.
  Choices, dates and checkboxes use the send form's `FieldInput` inputs.
- **On a phone** (a coarse pointer or a viewport under 640 px): the page fits the width. Tapping a field opens a bottom
  sheet titled **Enter {field label}**, with a large input of the field's type (`FieldInput`), **Cancel** and **Save**.
  Save writes the value into the field, drawn exactly as on a computer (same font, size, centring) and closes the
  sheet; Cancel leaves the field as it was. The field stays in view above the sheet. The guide's button opens the
  sheet for the field it points at.
- **Checks at the box**, by the one rule (`review.formats`), as the value is entered; "Too long for its box" by the
  Phase 7b fit check (shrunk down to the smallest size, refused beyond it). Save is disabled while the value is not
  valid; the reason is said under the input.

### 4.5 Conditions, drafts, viewed

- **Conditional fields** appear and go as answers change, by the same rule as the send (`conditions.askedFields` on
  the page, `sending.asked` on the server). A field that is no longer asked loses its value (and its draft).
- **Drafts**: each field is saved about a second after the person stops typing (or on Save on a phone) as a draft only
  they can see. Leaving, Finish later, or a session ending loses nothing. Drafts become values only at submit.
- **Viewed**: when the document is first shown (after the code and consent), the page reports it once; the recipient
  becomes `viewed`, and the envelope too while it is `opened`. It is for the sender's timeline only: Submit never
  requires the person to have scrolled to the end, only their required fields, signature places and the checkbox.

### 4.6 Accessibility

Each input is named by its field label and party ("Client 1 · Full name"); the guide's moves move focus to the field
and announce it; touch targets are at least 44 px; a list of the person's fields (label, required, filled) is offered
for anyone who cannot work on the page, and filling from it is the same as on the page.

### 4.7 Data (in `0025_signing`)

```
signing_drafts                                  -- the person's values before submit; nobody else reads them
  recipient_id   uuid not null → envelope_recipients
  workspace_id   uuid not null
  field_id       uuid not null                  -- a field of the envelope's version (composite key with version)
  value          text not null                  -- already checked by review.formats
  updated_at     timestamptz not null default now()
  primary key (recipient_id, field_id)
```

### 4.8 Interface

| Method and path | Body | Answers |
|---|---|---|
| `GET /api/v1/sign/{r}/document` | — | Pages and sizes, the fields with their places, who fills each, each value the person may see, their drafts, the font and the text sizes |
| `GET /api/v1/sign/{r}/pdf` | — | The version's PDF (no values in it; values are drawn over it, as the send's preview) |
| `PUT /api/v1/sign/{r}/drafts/{field}` | `{ "value": "…" }` | 204; 422 with the rule's words at the field; 403 when the field is not theirs or not asked |
| `DELETE /api/v1/sign/{r}/drafts/{field}` | — | 204 (cleared) |
| `POST /api/v1/sign/{r}/viewed` | — | 204, once in effect |

All need the session and grant (§1.3), consent (§3) and the code when required (§2). Every answer is
`Cache-Control: no-store`.

### 4.9 Algorithms

The document view is O(F + P) for F fields and P places: one read of the version's fields and places (by the version's
index), one of the envelope's values and one of the person's drafts, then a filter by who may see each value. The
guide's order is a sort of the person's places by (page, top, left), O(k log k) for their k fields, done once on the
page; the next empty field is the first in that order not filled, O(k).

### 4.10 Edge cases

| Case | Behaviour |
|---|---|
| A long document | Pages load as they come into view, as in the console |
| Two signers at once | Each sees the other's submission after a reload (Phase 7 §3); their own fields are never touched by the other |
| A draft saved while the envelope is cancelled | The save is refused; the closed page |
| A draft for a field that is now hidden | Removed when the condition hides it, and ignored at submit |
| Every required field is filled by the sender already | The button reads **Complete** from the start (signature fields remain: a signer always signs) |
| A person with only optional fields left and signatures done | **Complete** |
| The pointer's field is scrolled away by hand | The pointer stays with the field; the button still moves to it |
| A phone turned sideways | The page fits the new width; the sheet and the pointer follow |

## 5. Signatures and initials

### 5.1 Adopting

The first signature or initials field the person clicks, or is guided to, opens **Your signature**:

- **Type**: their name and initials, filled from the recipient's name and editable, shown in each handwriting font to
  choose from.
- **Draw**: a pad for a finger, mouse or stylus (pointer events, pressure ignored), with **Clear**. Signature and
  initials are drawn separately.
- **Use saved** (5.4): only for a countersigner who has a saved signature.
- Under them: "By selecting Adopt and sign, I agree this is my electronic signature." and **Adopt and sign**.

### 5.2 Handwriting fonts: one list, easy to add to

The typesetting module's font list (`typesetting.fonts.FONTS`, Phase 7b) is the one list of fonts. Each font gains a
`use` (`"text"` for values, `"signature"` for typed signatures). Adding a handwriting font is its file and licence in
`typesetting/fonts/` and one entry in the list; the signer's page offers every `signature` font
(`GET /api/v1/fonts?use=signature`), served by the existing `GET /api/v1/fonts/{id}`, and the PDF embeds the same
file. A font's id names one file forever, so a signature typed in it is drawn with the same letters later. Three open
licence handwriting fonts to start; a font that lacks a letter of the person's name is not offered for that name (the
check uses the font's glyph table, O(length)).

### 5.3 Placing: one tap a place, Apply to all

1. **Each signature or initials place takes one tap** once adopted; the tap is the person's intent at that place,
   recorded with the time (`signing.place_signed` is not an audit event per tap; the taps are kept on the draft and
   their times go on the certificate's record of the submit, topic 6).
2. **Apply to all** appears in the top bar when the person has more than one signature place (and separately for
   initials): it places the adopted signature in every one of their signature places that is asked. It needs an
   adopted signature first (it opens Your signature when there is none) and says what it did: "Signed 3 places".
3. **Change** (in Your signature) replaces the adopted signature in every place already signed, so a document never
   holds two different signatures from one person.
4. **Placed in the box**: scaled to the box's height, aspect kept, centred; the same on screen and in the PDF (topic
   10). A typed signature is drawn as text in its font; a drawn one as vector strokes.

### 5.4 Saved signatures: Signora accounts only

- **A signer from outside adopts a signature for that envelope only.** Nothing of it is kept for their next
  envelope, even when their email matches a Signora account: a signer link proves an inbox, not an account.
- **A countersigner's signature is saved to their account on their first countersign** (topic 7) and offered in Your
  signature on every later one. Saving is not a choice for them: it is their account's signature. **Change** replaces
  it.
- **Never applied by itself**: a saved signature is offered in Your signature and still takes Adopt and a tap per place
  (or Apply to all).
- **The envelope's own copy**: what was adopted for an envelope is kept with that envelope (5.5) and never changes when
  the saved one does.

### 5.5 How a signature is kept

```
signing_signatures                              -- adopted for one envelope: evidence, never changed after submit
  recipient_id   uuid not null → envelope_recipients
  workspace_id   uuid not null
  kind           text not null check (kind in ('signature','initials'))
  method         text not null check (method in ('typed','drawn'))
  text           text                           -- typed: 1-100 characters
  font           text                           -- typed: a font with use 'signature'
  strokes        jsonb                          -- drawn: [[x,y],...] per stroke, in a 0-1000 x 0-400 box
  sha256         bytea not null                 -- of the canonical JSON of the above
  adopted_at     timestamptz not null default now()
  primary key (recipient_id, kind)

saved_signatures                                -- a Signora user's, for countersigning
  user_id        uuid not null → users
  kind           text not null
  method, text, font, strokes, sha256           -- as above
  saved_at       timestamptz not null default now()
  primary key (user_id, kind)
```

A drawing: at most 50 strokes and 5 000 points; integer coordinates; at least 30 units of ink in total (a dot or a
blank pad is refused: "Draw your signature"). Strokes are smoothed on the page before they are sent, never on the
server, so what was seen is what is kept. Checks O(points).

### 5.6 Signing dates and date fields

- **A signing date** shows "Added when you sign" and is filled at submit with the server's time, in the envelope's
  time zone and the field's format (Phase 7c). It is never typed, picked or guided, so it cannot be backdated.
- **Every other full date the signer fills** opens the design system's date picker: in the phone's bottom sheet
  (§4.4), and beside the field on a computer (a popover in the top layer, placed like `Select`'s list). The picked
  date is drawn in the field's format.
- **Day, month and year parts** (Phase 7c) use the same inputs and typing rules as the send's Details step, one
  component (`FieldInput`): a day 1–31, a month from the list of names (or as a number where the format says so),
  a year of two or four digits as its format says; nothing else can be typed. The server checks each with the same
  rule (`review.formats.check_value`), so the page and the server never disagree.
- Each part is checked alone, as in the send: a day of 31 with a month of February is not refused, because the
  version does not record which parts make one date. Recorded as a known limit (§15).

### 5.7 Interface

| Method and path | Body | Answers |
|---|---|---|
| `GET /api/v1/sign/{r}/signature` | — | The adopted signature and initials (and, for a countersigner, the saved ones, 5.4) |
| `PUT /api/v1/sign/{r}/signature/{kind}` | `{ method, text?, font?, strokes? }` | 200 with its sha256; 422 with the reason |
| `PUT /api/v1/sign/{r}/drafts/{field}` | `{ "value": "signed" }` for a signature place | 204 (the tap); 409 `adopt-first` |
| `POST /api/v1/sign/{r}/apply-all/{kind}` | — | 200 `{ placed: n }`; 409 `adopt-first` |

### 5.8 Edge cases

| Case | Behaviour |
|---|---|
| A name with letters no handwriting font has | Only fonts that have them are offered; none: "Draw your signature instead" |
| A blank or tiny drawing | Adopt disabled, the reason said |
| The signature changed after places were signed | Every signed place takes the new one (5.3.3) |
| Apply to all with a place hidden by a condition | Only asked places are signed |

## 6. Submit

### 6.1 The Submit block

At the end of the document, after the last page:

- The statement: "By selecting Sign and submit, I agree to sign this document electronically and to be bound by it,
  the same as a handwritten signature."
- The checkbox "I've reviewed this document and this is my signature" (the guide's last stop, §4.3).
- **Sign and submit**, enabled only when every required field that is asked holds
  a valid value, every signature and initials place is signed (by its tap or by Apply to all, §5.3: either counts),
  and the box is ticked. While it is disabled one line says what is missing ("2 fields left", "Sign 1 more place",
  "Tick the box to confirm").

### 6.2 The server's check (nothing from the page is trusted)

`POST /api/v1/sign/{r}/submit` with an `Idempotency-Key` (the kernel's, Phase 1), in one transaction:

1. The session and grant (§1.3), the code when required (§2), the consent (§3).
2. `SELECT … FOR UPDATE` on the envelope's row: every submit, decline and cancel of one envelope takes this lock
   first, so they are applied one at a time and exactly one submit is the last signer's.
3. Under the lock: the envelope is open and before `expires_at`; the recipient is not `signed` or `declined`, and it
   is their stage (a countersigner only once the envelope is `signed`).
4. The value set: the sender's values, every earlier submitter's, and this person's drafts. The conditions are worked
   out again over all of it (`sending.asked`); drafts for fields not asked are dropped.
5. Each of this person's asked values is checked again by `review.formats.check_value` and the Phase 7b fit check;
   each required asked field has a value; each signature and initials place is signed; the adopted signature and
   initials exist for every kind placed.
6. Anything wrong: 422 `submit-incomplete` with `{ field_id, code, message }` for each, and nothing is written; the
   page's guide goes to the first.

### 6.3 What a submit writes (same transaction)

1. The drafts become `envelope_values` rows (`given_by = 'recipient'`, `recipient_id`); each signing date field gets the
   transaction's time in the envelope's zone and the field's format (§5.6); signature places get a value naming the
   adopted signature's sha256.
2. `signing_signatures` for the recipient are frozen (a trigger refuses changes once the recipient is `signed`).
3. The recipient: `status = 'signed'`, `signed_at = now()`, by
   `UPDATE … WHERE id = :r AND status NOT IN ('signed','declined')` (the guarded update: a repeat changes nothing).
   Their drafts are deleted. For a countersigner, the adopted signature becomes their saved one (§5.4).
4. Audit `signing.signed`: IP, user agent, verification method, consent version, the sha256 of the canonical JSON of
   their values, and of each signature.
5. When every signer is now `signed`: the envelope's `status = 'signed'` and the countersigners' turn starts (topic 7);
   with no countersigners, completion is queued instead (topic 12). Both are jobs written in this transaction (the
   outbox, Phase 1), so they happen exactly when the submit commits.

The answer is 200 `{ signed_at, next: 'done' }`. A repeat with the same key returns the stored answer; a repeat with a
new key after signing returns the same 200 (the guarded update found nothing to change).

### 6.4 Algorithms

O(F + P) for the version's F fields and P places: one read of each set, the conditions in one pass over the
dependency order (Phase 7 §17.3, O(F)), each value checked in O(length), the fit check O(length) per place. Writes are
a constant number of statements (multi-row inserts). The "is everyone signed" test is one count over the envelope's
recipients by the envelope's index, under the lock.

### 6.5 Edge cases

| Case | Behaviour |
|---|---|
| Double click, or a retry after a dropped connection | One signing; the same answer (6.3) |
| Two signers submit at the same moment | The lock orders them; the second sees the first as signed and is the last if everyone else is |
| A decline or cancel lands just before | Under the lock the envelope is closed: the closed page |
| Expiry passes while filling in | Refused at check 3: the closed page |
| The session ends on the Submit block | Nothing is lost (drafts); link, code, then back at the Submit block |
| An earlier signer's answer changed which fields are asked | The server's working-out decides; the page reloads the document and the guide resumes |
| Apply to all signed every place, none tapped | Counts as signed (6.1) |
| A value valid on the page but refused by the server | Said at its field; the guide goes there |

## 7. The countersigners' turn

### 7.1 Rules

1. **It starts when the last signer submits**, in that transaction (§6.3.5): each countersigner goes from `waiting` to
   `sent` and is emailed "{Company}: your countersignature is needed on {template}" (who signed, a button to the
   envelope in Signora). The sender and the envelope's Also notify list get "All signers have signed {template}".
2. **A countersigner signs in Signora, signed in to their account**, never through a signer link or an email code:
   they are a member of the company, and their account's sign-in is the proof of who they are (the certificate says
   "Signora sign-in"). The email's button opens their countersign page, `/countersign/{recipient_id}` (the inbox is
   `/countersign`); signed out, it goes through sign-in and back to it. The Copy signing link and Send again of a
   countersigner give that page's address, not a token.
3. **Every rule of the signer's screen applies** (§4–§6): the viewer, the guide (Start, Next, Complete), the phone's
   sheet, drafts, the date picker, consent once, the Submit block, the server's check and the lock. Only the proof of
   who they are differs (sign-in for §1–§2).
4. **Their signature is saved on first sign**: adopted once (§5.1), saved to their account (§5.4), and offered on every
   later countersign. Save is always on for a countersigner (it is their own account's signature); Change replaces it.
5. **What a countersigner sees**: every value the signers gave. They sign for the company that receives the agreement,
   and the completed copy shows everything; a field private to its party (Phase 6) is kept from other signers, not
   from the company.
6. **Countersigners sign in any order**; the last one's submit queues completion (topic 12). A countersigner may
   decline (topic 8).
7. **Only the designated user signs their place**: the page and every request check that the signed-in user is the
   recipient's `user_id`, still an active member, with the envelope at their stage.

### 7.2 To countersign: a personal inbox, with a dot

- **One page for the signed-in user**, `/countersign`, reached from **To countersign** in the side navigation. It lists
  every envelope waiting for their countersignature, across all their departments: title, template, department,
  signers (all signed), when the last signed, expiry; newest turn first. A row opens the countersign page. Empty, it
  says "Nothing to countersign."
- **The dot** (with the count, "To countersign · 2") is on the navigation entry, and only when the count is above
  zero. It counts envelopes whose signers have all signed and that the user has not yet signed: being chosen as a
  countersigner on a send shows nothing until it is their turn.
- One query, `GET /api/v1/me/countersign?cursor=`: recipients with `kind = 'countersigner'`, `user_id = me`,
  `status IN ('sent','opened','viewed')`, the envelope open and before expiry; the count is
  `GET /api/v1/me/countersign/count`. An index on `envelope_recipients (user_id, status) WHERE kind =
  'countersigner'` makes both an index range, O(k) for the user's k waiting envelopes.
- The count is read with the navigation and again when the page regains focus (no polling, no push).

### 7.3 Interface

| Method and path | Answers |
|---|---|
| `GET /api/v1/me/countersign?cursor=` | The user's waiting countersigns across departments, newest turn first, 50 a page |
| `GET /api/v1/me/countersign/count` | `{ n }` for the navigation's dot |
| `/api/v1/countersign/{r}/…` | The signer routes of §3–§6 (`document`, `pdf`, `drafts`, `signature`, `apply-all`, `viewed`, `consent`, `submit`, `decline`), authorized by the console session (CSRF, Phase 2) and §7.1.7 instead of a signing grant |

The signing service takes "who is acting" as one value (a signer's grant or a countersigner's user), so both routes
run the same code.

### 7.4 Edge cases

| Case | Behaviour |
|---|---|
| A countersigner left the company before their turn | They cannot sign (§7.1.7); the envelope page says "{Name} is no longer a member. Choose another countersigner."; the change emails the new one |
| A countersigner is changed after their turn began | The old one's list loses it at once; the new one is emailed and sees the dot |
| The countersigner's email bounces | As any failed email: Retry on the envelope page; the dot in Signora still shows it |
| Two countersigners sign at the same moment | The envelope's lock (§6.2); the last of them queues completion once |
| One person is both a signer and a countersigner | Refused at the send unless confirmed (Phase 7); then a signer link for one and the countersign page for the other |
| A signed-in user who is not the countersigner opens the page | 404, as for an envelope they cannot see |

## 8. Decline

### 8.1 Rules

1. **A decline is final.** It declines the envelope for everyone; every link closes; it cannot be undone by opening the
   link again. Accidental declines are prevented, not reversed.
2. **Prevented**: Decline is a quiet secondary action (never beside the main button's position), and it opens a
   confirmation: "Declining stops this request for everyone. {Company} will see your reason.", a reason (required,
   up to 500 characters), **Decline to sign** and **Go back**. The consent screen's Decline opens the same confirmation.
3. **Finish later** is offered on the signer's screen, so leaving never needs a decline; drafts are kept (§4.5).
4. **Send again** on a declined envelope (and, with Phase 10, an expired or cancelled one) opens the send modal filled
   with the same template version, recipients, values and settings, the decline's reason shown at its top. Anything
   can be corrected; it is a new envelope with new links; the declined one stays as it was, for the record.

### 8.2 What a decline does

`POST /api/v1/sign/{r}/decline` (and `/api/v1/countersign/{r}/decline`) with `{ "reason": "…" }` and an
`Idempotency-Key`, in one transaction under the envelope's lock (§6.2):

1. Checks: the session and grant (or the countersigner's sign-in), the code when required; the envelope open and
   before expiry; the person not `signed` or `declined`, and at their stage. Consent is not required: declining is how
   consent is withdrawn (§3).
2. The recipient: `status = 'declined'`, `declined_at = now()`, `decline_reason`; the envelope: `status = 'declined'`.
   Every link and session of the envelope stops working at its next request (§1.1.10). Drafts are deleted.
3. Audit `signing.declined` with the reason, IP and user agent.
4. Emails (outbox, in the transaction):
   - the sender and the Also notify list: "{Name} declined {template}", with the reason and a button to the envelope;
   - every signer who was emailed, signed or not, except the one declining: "{Template} was declined. Nothing more is
     needed from you." (no reason: it was written to the company);
   - countersigners still `waiting`: nothing (it never became their turn); countersigners whose turn had begun: the
     same as signers.
5. The envelope page shows who declined, when, and why, with **Send again** (§8.1.4).

### 8.3 Data (in `0025_signing`)

`envelope_recipients` gains `declined_at timestamptz` and `decline_reason text`, with a check that both are set
exactly when `status = 'declined'` and the reason is 1–500 characters after trimming.

### 8.4 Edge cases

| Case | Behaviour |
|---|---|
| Two people decline at the same moment | The lock orders them; the second sees the closed page |
| A decline while another person submits | Whichever takes the lock first is applied; the other sees the closed page or the declined envelope |
| A repeated decline (double click) | The same answer; one decline, one set of emails |
| A reason of spaces | Refused at the box: "Tell them why" |
| Send again after the template was archived | Refused: "This template is archived. Restore it to send again." |
| Send again after a newer version was approved | The declined envelope's version is offered (it is still approved); the sender may pick the newer one in the Template step |

## 9. The done screen

### 9.1 The done screen

Shown at once after Sign and submit:

- **"Signed. Thank you, Maya."** (the recipient's first name).
- **Signed at** "Nov 11, 2026 at 9:14:22 AM PST", in the person's own time zone (the browser's), to the second. The
  certificate uses the envelope's zone (Phase 7 §5).
- **Verified by** "Email code to m•••@example.com" (or "Email link" with the code off).
- **Download a copy**: a button; the PDF as signed so far, made by the signed PDF's renderer (topic 10) with only what
  this person may see (§4.2), named "{template} - signed by {name}.pdf".
- **A subtle line** under it on what happens next: "Waiting for Leo Chen to sign, then Hale & Ward LLP countersigns.
  You'll get the completed copy by email." When the person was the last signer: "Waiting for Hale & Ward LLP to
  countersign. You'll get the completed copy by email." When nothing is left: "Done. You'll get the completed copy by
  email shortly."

Opening the link again later brings the person here (after the code) until the envelope completes; then the link
closes (§1.1.3) and the completed copy is in their email (topic 12).

A countersigner returns to their inbox (`/countersign`) with a short notice, "Countersigned", or, when they were the
last, "Completed. Everyone gets the signed copy."

### 9.2 No email until completion

Nothing is emailed to a signer when they sign: the done screen and **Download a copy** confirm it, and the completed
copy reaches everyone when the envelope completes (topic 12).

### 9.3 Interface

| Method and path | Answers |
|---|---|
| `GET /api/v1/sign/{r}/done` | `{ signed_at, verified_by, waiting_for: [names], countersigning_company, completed }` |
| `GET /api/v1/sign/{r}/copy.pdf` | The copy as signed so far (`Content-Disposition: attachment`), rendered on request |

The copy is rendered on request, not stored: it is a view of values already kept, O(pages + places).

### 9.4 Edge cases

| Case | Behaviour |
|---|---|
| Download while another signer is signing | The copy shows what was submitted when it was made |
| Download after the envelope completed | The link is closed; the completed copy is in their email |


## 10. The signed PDF

### 10.1 Rules

1. **The original is never changed.** The version's PDF stays as approved. The signed PDF is a new file: the
   original's pages with every value and signature written into the page content.
2. **One renderer** (a new `rendering` module, PyMuPDF) makes the copy as signed so far (§9), the completed document
   (topic 12) and the console's download. It draws each value with typesetting's rules (the envelope's font, the text
   size kept at approval, `fit.place_size`, baseline, centring, Phase 7b); the browser's overlay follows the same rules
   and both run the shared vectors, so what was seen is what is printed.
3. **What is drawn**: text and dates as stored, in the field's format; a checkbox as a check mark; a choice as a mark
   at the chosen option; a typed signature in its font and a drawn one as vector strokes, scaled to the box's height,
   aspect kept, centred. Fonts are embedded as subsets.
4. **Signed by frames**: each signature and initials place gets a thin bracket inside its box with "Signed by:" above
   and the first 16 hexadecimal characters of the signature's sha256 below (initials: the ID only). A box under 24 pt
   high gets the signature alone.
5. **Envelope ID on every page**: a line in the top margin, 7 pt, grey, "Signora envelope ID: {envelope id}".
6. **Flattened**: values are page content, not form fields; the original's form fields, annotations and scripts are
   removed from the output, so nothing in it can be edited or run.
7. **The completed document is made once** by the completion job (topic 12), stored in the blob store, its sha256 kept
   on the envelope; every later download serves that file. The copy as signed so far is rendered on request and never
   stored (§9.3).
8. **Who sees what**: the completed document shows every value; the copy so far leaves out what that person may not
   see (§4.2).
9. **No digital seal in this phase**: a seal that PDF readers show as valid needs a certificate from a trusted
   authority; a self-made one reads as "validity unknown". The certificate's hashes (topic 11) are the tamper
   evidence. Listed for hardening.

### 10.2 Interface (inside the API, no HTTP of its own)

```
rendering.render(pdf: bytes, pages: list[PageBox], items: list[DrawItem], *, envelope_id: UUID, font: str) -> bytes
DrawItem = Text(place, value, size) | Mark(place) | TypedSignature(place, text, font, sig_id)
         | DrawnSignature(place, strokes, sig_id)
```

`envelopes`/`signing` build the items (what may be seen, formatted values); `rendering` only draws. Pure apart from
the PDF library; O(pages + places + stroke points).

### 10.3 Edge cases

| Case | Behaviour |
|---|---|
| A value too long for its box | Cannot reach the renderer: refused at its box and at submit (§4.4, §6.2) |
| A rotated or cropped page | Drawn in the page's visible frame with the viewer's coordinates (`page.rect`, rotation applied) |
| An original with form fields or links | Fields and scripts removed; the page's printed content kept |
| A 100-page template | Under 3 s to render, measured in a test |

## 11. The certificate of completion

### 11.1 Content

A separate PDF (not appended to the document), in the design system's print style, every time in the envelope's zone:

1. **Header**: envelope ID, title, template, page count, number of signatures and initials, sent by (name, email),
   status "Completed", the time zone used.
2. **One block per signer, then per countersigner**, in signing order: name, email; verified by ("Email code",
   "Email link" or "Signora sign-in"); the signature as signed, how it was adopted ("Typed, {font}" or "Drawn") and its
   Signature ID (the first 16 hexadecimal characters of its sha256, as in its frame, §10.1.4); the IP address it was
   signed from; Sent, Viewed, Signed times; Electronic records disclosure "Accepted" with its time and version.
3. **Copies**: each person who receives a copy, their email, when the copy was sent.
4. **Envelope summary**: sent, first viewed, signing finished (all signers), completed.
5. **Integrity**: the sha256 of the version's original PDF and of the completed document (possible because the
   certificate is a separate file); anyone can hash the file they hold and compare.
6. **The disclosure**: the full text of each version accepted, on the last page.

Not on it, because Signora has no such feature: in-person signing, witnesses, notaries, payments, identity checks.

### 11.2 Making it

- Read only from what is already kept: recipients, `signing_consents`, `signing_signatures`, the audit chain's events
  (`signing.opened`, `signing.viewed`, `signing.signed`, with IP and user agent). Nothing is written for it.
- Made once by the completion job right after the completed document (topic 12), by the `rendering` module, stored in
  the blob store with its own sha256 on the envelope; never remade.
- O(R + E) for R recipients and the envelope's E audit events (one read of each, by the envelope's indexes).

### 11.3 Edge cases

| Case | Behaviour |
|---|---|
| A recipient's email was corrected during the envelope | The email they signed with; the change is in the envelope summary |
| A signer with Require email code off | "Email link" |
| A long name or email | Wrapped within its column, never cut |
| Many recipients | The blocks continue over pages; the header repeats the envelope ID on each page |

## 12. Completion

### 12.1 The job

`envelope.complete`, queued in the transaction of the last submit (the last countersigner's, or the last signer's
when there are none, §6.3.5), run by the worker:

1. If the envelope is `completed`, stop (a repeat does nothing).
2. Render the completed document (§10) and the certificate (§11); store each in the blob store under a key made from
   the envelope id (`envelopes/{id}/signed.pdf`, `envelopes/{id}/certificate.pdf`), so a retry overwrites the same
   objects and never leaves a second copy.
3. One transaction under the envelope's lock: `status = 'completed'`, `completed_at`, the two blob keys and their
   sha256; every link and session closes (§1.1.10); audit `envelope.completed` with both hashes; the completed emails
   queued (12.2). Guarded by `WHERE status = 'signed'`, so only one run completes it.

Failure: the job retries with a growing wait (the kernel's job retries, Phase 1). Meanwhile the envelope stays
`signed` and its page says "Making the signed copy…"; after the last retry it says "The signed copy couldn't be made"
with **Try again** (re-queues the job). Nothing signed is lost: every value and signature is already kept.

### 12.2 The completed email

To every signer, countersigner, person receiving a copy, the sender and the Also notify list, one each (dedupe key
`sign_completed:{envelope}:{email}`; one person on two roles gets one): "{Template} is complete. Everyone has
signed.", who signed, and the signed document and the certificate attached as two PDFs. When the two together exceed
20 MB the email goes without them: "The signed copy is too large to email. Ask {sender} for it."

### 12.3 In the console

The envelope page of a completed envelope: **Download** with Document, Certificate, and Combined (the document then
the certificate, joined on request, not stored); "Completed" with its time in the timeline. The Envelopes tab and the
counts already treat `completed` as signed (Phase 7).

`GET /api/v1/envelopes/{e}/download?part=document|certificate|combined` (permission to see sends), serving the stored
files; O(1) reads plus the join for Combined, O(pages).

### 12.4 Edge cases

| Case | Behaviour |
|---|---|
| Two last submits at the same moment | The envelope's lock makes one the last; the job is queued once |
| The job runs twice | The second stops at step 1, or its step 3 updates nothing |
| One person's completed email fails | Their delivery record and Retry on the envelope page; the others still get theirs |
| A cancel while the job runs | Refused: every party has signed (the envelope is `signed`, waiting only for the job) |

## 13. Security

1. **Limits**, through the kernel's one `RateLimiter` (Phase 2 §7.1; keys namespaced `sign:…`), 429 `rate-limited`
   with `Retry-After` and "Too many tries. Try again in a minute.":

   | Action | Limit | Key |
   |---|---|---|
   | Open a link | 20 a minute | IP |
   | Verify a code | 10 a minute | IP |
   | Ask for a code | 60 s apart, 5 an hour | person (kept in `signing_codes`, §2.2) |
   | Wrong codes | 5 a code | person (`signing_codes.wrong_tries`) |
   | Save a draft | 120 a minute | browser session |
   | Submit, decline | 10 a minute | browser session |

   The person-keyed limits are in Postgres, so they hold across restarts and API processes. The IP and session limits
   use the in-memory limiter, correct for this deployment's single API process; running several processes is the
   Redis backend behind the same protocol and one setting (`RATE_LIMITER_BACKEND`), with no change to callers.
2. **Headers** on `/s/*`, `/sign/*`, `/countersign/*` and `/api/v1/sign/*`: `Referrer-Policy: no-referrer`,
   `X-Robots-Tag: noindex, nofollow`, `Cache-Control: no-store`, `X-Frame-Options: DENY` (and CSP
   `frame-ancestors 'none'`), with the app's nonce-based Content Security Policy (`proxy.ts`). `/countersign` joins the
   proxy's console paths (sign-in required).
3. **Nothing secret in logs**: a link token travels only in a request body; the logger's redaction (kernel
   `logging`) gains `token`, `code` and the signer cookie's name; codes and tokens are never in an exception message or
   an audit event.
4. **Tenant isolation**: every signing table carries `workspace_id` in a composite key with its recipient, as Phase 7's
   tables do; a signer request reaches only the recipient its grant names, and a countersign request only a recipient
   whose `user_id` is the signed-in user.
5. **Sessions apart**: the signer's cookie gives no console access and the console's gives no signer access; a
   countersigner uses only the console's sign-in.
6. **Audit**: every signing event is on the envelope's hash-chained audit trail (Phase 1) with IP and user agent.
7. **Uploaded strokes and text are data**: a signature's strokes are integers checked for count and range, a typed
   signature's text for length; nothing a signer sends is ever drawn as markup.

# Low-level design

## 14. Requirements

### 14.1 Functional

| # | Requirement | Topic |
|---|---|---|
| FR-S1 | A signing link becomes a browser session; closed or forged links answer the same | 1 |
| FR-S2 | The email code, when required, before anything of the document is shown | 2 |
| FR-S3 | Consent to electronic records once per person, versioned | 3 |
| FR-S4 | The signer's screen: own fields, the guide, phone sheet, date picker, drafts, who sees what | 4 |
| FR-S5 | Signatures and initials typed or drawn, one tap a place, Apply to all; countersigners' saved | 5 |
| FR-S6 | Submit re-checks everything on the server, once, under the envelope's lock | 6 |
| FR-S7 | Countersigners' turn after the last signer; their inbox with a dot; sign-in instead of a code | 7 |
| FR-S8 | Decline is final, with a reason; Send again for the sender | 8 |
| FR-S9 | The done screen with Download a copy; no email until completion | 9 |
| FR-S10 | The signed PDF: original pages, values and signatures written in, envelope ID, Signed by frames, flattened | 10 |
| FR-S11 | The certificate of completion as a separate PDF with each person's events and the hashes | 11 |
| FR-S12 | Completion: one job, the completed email with both PDFs, downloads | 12 |
| FR-S13 | Limits, headers, logs, isolation | 13 |

### 14.2 Non-functional

| # | Requirement | Threshold |
|---|---|---|
| NFR-S1 | Opening a link, a draft save | p95 under 100 ms on the test database |
| NFR-S2 | Submit for 50 fields, 100 places | under 300 ms |
| NFR-S3 | Render a 100-page signed PDF | under 3 s |
| NFR-S4 | Repeat-safety | no duplicate signing, decline, completion or email under repeats and races (tests) |
| NFR-S5 | Parity | the page's overlay and the PDF place every value by the same rules (shared vectors) |
| NFR-S6 | Phones | the whole path usable at 360 px wide; touch targets 44 px |
| NFR-S7 | Accessibility | every input named; the guide announced; reduced motion honoured |

## 15. Data design (migration `0025_signing`)

New, owned by `signing`: `signing_sessions`, `signing_grants` (§1.4), `signing_codes` (§2.2), `signing_consents`
(§3.2), `signing_drafts` (§4.7), `signing_signatures`, `saved_signatures` (§5.5).

Changed, owned by `envelopes`: `envelope_recipients` gains `declined_at`, `decline_reason` (§8.3) and the index
`(user_id, status) WHERE kind = 'countersigner'` (§7.2); `envelopes` gains `signed_blob`, `signed_sha256`,
`certificate_blob`, `certificate_sha256` (set together, once, when `completed`).

Changed, owned by `notifications`: `email_attachments (email_id, position, blob_key, filename, content_type)`; an
email keeps blob keys, not bytes, and the transport reads them when it sends (an email's body is still not kept after
delivery, Phase 2 §1a).

Triggers: `signing_consents` insert only; `signing_signatures` frozen once its recipient is `signed`; the envelope's
completed files set once. Downgrade drops the new tables and columns.

## 16. Modules

| Module | Owns | Depends on |
|---|---|---|
| `signing` (new) | the signer and countersigner flows (§1–§9), the completion job (§12) | `envelopes` (its public interface: read an envelope for signing, record opened/viewed/signed/declined, store values, complete), `review` (`formats`, conditions), `typesetting`, `rendering`, `identity_access` (sign-in, `normalize_email`), `notifications`, `audit`, `kernel` |
| `rendering` (new) | drawing values and signatures onto a PDF, the certificate (§10–§11) | `typesetting`, `kernel` (pure apart from PyMuPDF) |
| `envelopes` | its tables and their state rules; gains the transitions this phase causes, behind functions `signing` calls | unchanged; never imports `signing` |

Import contracts gain `signing` and `rendering` in the layers, `rendering` in the pure modules.

Web: `features/signing` (the `/s/[token]` exchange, `/sign/[recipientId]`: code, consent, the document, the done and
closed pages), `features/countersign` (the inbox and `/countersign/[recipientId]`, reusing the signing screen), and in
the design system: `DatePicker`, `BottomSheet`, `GuidePointer`, `SignaturePad`, `SignatureDialog`.

## 17. Tests

- **API, against Postgres**: each route's success and every refusal of §1.2, §2.3, §3.3, §4.8, §5.7, §6.2, §8.2;
  races (two submits, submit and decline, two opens) with two connections; repeat-safety by idempotency key and by
  guarded update; who sees what in the document view (other signers' private values never in the answer); limits.
- **Pure**: rendering against the shared vectors (positions, sizes, centring) and a 100-page timing; the certificate's
  content from a fixed envelope; the guide's order; signature checks.
- **Web**: the guide's states (Start, Next, Complete, the checkbox), the phone sheet's Save and Cancel, the date
  picker, Apply to all, the Submit block's reasons, the closed and done pages, the inbox and its dot.
- **End to end on the live site**: send, two signers on two browsers, countersign signed in, the completed email in
  Mailpit with both PDFs, hashes checked against the files.

## 18. Task tracker

| # | Task | Status | Evidence |
|---|---|---|---|
| 8.1 | This design (§1–§17) | done | this document |
| 8.2 | Migration 0025, models, triggers | done | `0025_signing.py`; `signing/models.py`, envelopes and notifications models; recipients gain `(id, workspace_id)` and `(id, workspace_id, version_id)` keys for the signing tables (foreign keys to recipients named by hand, under Postgres's 63 characters); import contracts for `signing`. Tests: `test_tables.py` (11: consent insert only, a signature frozen once signed, a signature's shape, a decline recorded, completed files set together once, attachments), the schema test, the downgrade and upgrade round trip. The envelopes functions `signing` calls come with the tasks that call them |
| 8.3 | Opening a link, sessions, grants; `/s` and `/sign` pages; the closed page | done | `signing/` (`sessions.py`: cookie `__Host-signora_sign`, 30 min idle from `.env`, 12 h at most, grants that a newer link version replaces with its verification; `service.py`: `open_link`, `signer` (checked on every request), `state`; `domain.py`: `mask_email`, `next_step`; `errors.py`: `link-closed`, `session-ended`); `envelopes.recipients` (`recipient_for_signing`, `record_opened`); identity exports its token helpers (one definition); `signing.opened` on the envelope's audit chain. Web: `/s/[token]` (one exchange per token, then `/sign/{id}`), `/sign/[recipientId]`, the closed and session-ended screens, both routes noindex and no-referrer (Caddy already keeps tokens out of its access log). Tests: `test_open.py` (7: a session and opened once, no code means consent next, five unusable links answer alike, an open page closes at expiry, a corrected email, two people in one browser, idle end), `signing.test.tsx` (4) |
| 8.4 | The email code | done | `signing/codes.py` (a code key derived for this purpose; HMAC of recipient, link version and code; the row's lock orders tries and new codes; a wrong try is committed before the refusal; ten minutes and five tries from `.env`; a minute between codes, five an hour), `trail.py` (signing events on the envelope's chain), `POST …/code` and `…/verify`; the envelope emails' date wording made public (`moment_in_words`, one definition); the kernel's retry base made public (`RetryAfter`). Web: `CodeField` in the design system (one input drawn as six boxes, `one-time-code`, paste, digits only), `VerifyStep` (sent as the step opens, Send a new code with its countdown). Tests: `test_code.py` (8: sent and kept, single use, a wrong try kept, the minute's wait, five wrong tries, ten minutes, five an hour, per browser, a corrected email, no code asked), `signing.test.tsx` |
| 8.5 | Consent | done | `signing/consent.py` (the disclosure's four paragraphs, its version and the box's words in one place; the record with the request's IP and user agent, repeat-safe), `POST …/consent` (`verify-first`, `disclosure-changed`), the disclosure in the signer's state; the consent's IP and user agent may be unknown (the server records an address only when a valid one reached it). Web: `ConsentStep` (the paragraphs, the box, Continue). Tests: `test_consent.py` (3: once per person across browsers with its version and browser recorded, the code first, a changed disclosure), `signing.test.tsx`. Decline from this screen comes with 8.10 |
| 8.6 | The document view, drafts, viewed (API) | done | `signing/document.py` (pure: every field with what this person may see; their name and the address it was sent to locked; a countersigner's values never sent to a signer, nor another person's private value; a countersigner sees all), `drafts.py` (checked by `check_value` and the fit check as saved; not theirs, locked or not asked refused; a draft goes when its field stops being asked), `GET …/document`, `GET …/pdf`, `PUT`/`DELETE …/drafts/{field}`, `POST …/viewed` (once; the envelope too while opened), all after the code and consent; documents' `version_for_signing` (no console user); envelopes exports `form_fields_of` (the send form's own per-field builder, now shared), `asked`, `fits`, `name_part`, `envelope_values`, `record_viewed`. Tests: `test_document.py` (7), `test_visibility.py` (3: another signer's private value, a countersigner's value, a sender's private value) |
| 8.7 | The signer's screen: overlay inputs, the guide, phone sheet, `DatePicker`, Finish later | done | `features/signing/SigningScreen.tsx` (the pinned bar with the count, the guide's button and Finish later; the viewer with each page's fields: typed straight into the box on a computer in the envelope's font at the PDF's size, ticks and options toggled in place, other types in a panel beside the box; on a phone every field in a bottom sheet with Save and Cancel; other people's boxes faint and named, private and countersigner boxes marked; drafts saved 0.8 s after typing stops, a field no longer asked dropping its value as on the server; viewed reported once; the Submit block's statement, box and Sign and submit with what is missing), `guide.ts` (reading order, what is left, Start, Next, Complete, the pointer's words). Design system: `DatePicker` (type a date month first or as YYYY-MM-DD, or choose it from a calendar: arrows, Page Up and Down, a year list), now the input of every whole date, the send's too; `GuidePointer` (a ring and a curved arrow drawn in once, in the top layer, following the field, never catching a click); `Dialog` placed along the bottom for a phone's sheet; `useAnchored` (what opens beside a trigger: Select's own logic, now shared); the document's typesetting, conditions, inputs and overlay moved to `shared/document` (119b272). Tests: `guide.test.ts` (6), `screen.test.tsx` (3), `DatePicker.test.tsx` (3), `signing.test.tsx`. Sign and submit is wired in 8.9; signature boxes in 8.8 |
| 8.8 | Signatures: fonts' `use`, adopt, `SignatureDialog` (type, draw), one tap, Apply to all | done | `signing/signatures.py` (a drawing: integer points in 1000 x 400, at most 50 strokes and 5 000 points, at least 30 units of ink; a typed one: 1–100 characters in a font whose `use` is `signature` and that draws every letter; the fingerprint of its canonical JSON), `PUT …/signature/{kind}` (adopt or change; every signed place takes the new one), `GET …/signature`, a tap as the draft `signed` (`adopt-first` before one is adopted), `POST …/apply-all/{kind}`; typesetting's fonts gain a `use`, `fonts_for`, `has_glyphs` and `GET /api/v1/fonts?use=`. Web: `SignaturePad` (pointer events, kept as whole points) and `SignatureMark` (scaled to the box's height, centred) in the design system, `SignatureDialog` (Type when there are styles, Draw, Adopt and sign), one tap a place, Sign all and Initial all when there is more than one place, Change signature. Tests: `test_signatures.py` (5), `screen.test.tsx`. Handwriting styles (owner's approval, 2026-11-11): Great Vibes, Allura and Sacramento, SIL OFL 1.1, from the Google Fonts repository, each with its licence in `typesetting/fonts/` (about 790 KB together); a name with letters none of them has is drawn instead |
| 8.9 | Submit (API and the Submit block) | done | `signing/submit.py` (under the envelope's lock: open and before expiry, not signed or declined, their turn; conditions worked out again over every value; each asked value checked again by `check_value` and the fit check, each required one present, each signature place signed with an adopted one; every refusal named by field id and nothing written; then the values once (their name, signatures as `signature:{id}`, signing dates on the day in the envelope's zone), signed by a guarded update, drafts gone, `signing.signed` with how they were verified, the consent's version and the fingerprint of their values; the last signer moves the envelope to `signed` and its countersigners to `sent`), `POST …/submit` (`Idempotency-Key`; a repeat answers as the first); envelopes' `lock_envelope`, `write_values`, `record_signed`, `unsigned`, `every_signer_signed`; drafts' `merged_values` (one read of what is given, locked and required). Web: Sign and submit (one key per press, kept until a definite answer), the server's word at each box and the guide to the first. Tests: `test_submit.py` (3), `screen.test.tsx`. The countersigners' email and completion follow in 8.11 and 8.14 |
| 8.10 | Decline and Send again | done | `signing/decline.py` (under the envelope's lock; after the code, no consent needed; the person and the envelope `declined` with the reason, final; drafts gone; `signing.declined` with the reason; the sender and the Also notify list emailed the reason with a button to the envelope, every other person already emailed told it is over, a countersigner whose turn never came told nothing), `POST …/decline` (`Idempotency-Key`; answers 200 so a replay is the same), `emails.py`; envelopes' `record_declined`, the recipient's `declined_at` and `decline_reason` on the envelope page. Web: Decline in the signer's bar and on the consent screen, a confirmation that asks why, the declined screen; on a declined envelope who declined, when and why, with Send again: the send modal opened from a draft of the same version, people, values and settings (`SendDraft`, `draftFrom`), the reason at its top. Tests: `test_decline.py` (4), `screen.test.tsx`, `sendAgain.test.ts` |
| 8.11 | Countersigning: routes, inbox, the navigation's dot, emails | done | The signing routes act for a countersigner signed in to Signora (`service.acting`: the console's session and CSRF check, the designated user, the envelope open, their turn; no email code, `code-not-required`), so their screen and every rule are the signer's; `turns.py` (when the last signer signs: each countersigner emailed a button to `/countersign/{id}`, the sender and the Also notify list told all signers have signed); a countersigner's adopted signature saved to their account at their submit and offered after (`saved`); `signora_sign_in` as how they were verified; envelopes' countersigner links (first email, reminders, Send again, Copy signing link) are their countersign page; `inbox.py` (`GET /api/v1/me/countersign`, newest turn first, keyset pages of 50; `…/count`). Web: To countersign in the navigation with a dot and the count above zero (read with the navigation and on focus), the inbox page, `/countersign/{id}` (signed out: the proxy sends to log in and back), Countersigned. Tests: `test_countersign.py` (3), `inbox.test.tsx` (3) |
| 8.12 | `rendering`: the signed PDF; the done screen and its copy | done | `rendering/draw.py` (the original's pages kept; text by typesetting's own fit, baseline and centring; a tick drawn as lines; a typed signature in its font and a drawn one as vector strokes, scaled to the box and centred, in a Signed by frame with the signature's ID when the box is 24 pt or taller; the envelope's ID on every page; form fields, annotations, links, scripts and open actions removed; fonts subset; rotated pages drawn as displayed), `signing/drawing.py` (an envelope's values as items, all of them or one person's view), `GET …/done`, `GET …/copy.pdf` (UTF-8 file names); the MuPDF lock made reentrant (a render measures widths inside its own hold: found as a deadlock in the first test run). Web: the done screen (thanks, the time signed in the person's zone to the second, how they were verified, Download a copy, what is next; Countersigned with the way back to the inbox); `LinkButton` gains `download`. Tests: `test_draw.py` (4: content where the preview puts it, nothing editable left, a rotated page, 100 pages in under 3 s: 0.5 s measured), `test_copy.py` (2), `signing.test.tsx`. Import contracts: rendering only draws |
| 8.13 | The certificate of completion | done | `rendering/certificate.py` (data in, PDF out, laid out by the PDF library's HTML layout over as many letter pages as it takes, in Liberation Sans: the header, each signer then countersigner with how they were verified, their signature drawn as signed with how it was adopted and its ID, the address they signed from, sent, viewed and signed times and the disclosure they accepted; copies; the envelope summary; both fingerprints; each accepted disclosure's text). Its data is gathered by completion (8.14). Tests: `test_certificate.py` (2: what it says, 25 people over pages) |
| 8.14 | Completion: the job, email attachments, the completed email, downloads | done | `signing/completion.py` (`envelope.complete`, queued in the last submit's transaction, once per envelope: reads in one short transaction, renders outside any, stores the document and the certificate content-addressed (a retry stores the same objects), then under the envelope's lock completes it once (`WHERE status = 'signed'`), audits both fingerprints and emails everyone (signers, countersigners, copies, the sender, Also notify; one each) with both PDFs, or without them over 20 MB; 5 attempts with the kernel's backoff), `certify.py` (the certificate's facts from what is kept), `jobs.py`; notifications carry attachments as blob references read at delivery (`AttachedFile`, both transports); the kernel's `BlobRef.token` and the one download-name helper (`kernel.http.attachment`); `GET /api/v1/envelopes/{e}/download?part=document|certificate|combined` (`rendering.combine`); `completed_at` on the envelope. Web: on a completed envelope its date and Download, Document, Certificate; while it is being made, Making the signed copy. Tests: `test_completion.py` (2: completed once with both stored and fingerprinted, everyone emailed both PDFs attached on delivery; the three downloads). Not built: Try again after the last attempt fails (§12.1), listed for hardening |
| 8.15 | Security: limits, headers, log redaction | done | `signing/limits.py` through the kernel's rate limiter: opening links 20 a minute and trying codes 10 a minute per address, saving drafts 120 a minute and submit or decline 10 a minute per person (a person's codes are limited in Postgres, 8.4); 429 `rate-limited` with `Retry-After`. Headers: the request proxy marks `/s/`, `/sign/` and `/countersign` pages `X-Robots-Tag: noindex, nofollow` and `Cache-Control: no-store`; Caddy does the same for `/api/v1/sign/*` (downloads included); Caddy already keeps tokens out of its access log and sends `no-referrer` and `DENY` framing everywhere. Logs: the kernel's redaction already masks `token`, `otp` and cookies, and signing logs no code or token. Isolation: every signing table keyed with its company (8.2); a countersigner's request is checked against their sign-in (8.11). Tests: `test_limits.py` (2) |
| 8.16 | Live check end to end, deploy, PR | done | Full check once after every task (owner, 2026-11-11): lint, types, 19 import contracts, 768 API tests, 342 web tests, build, contract check, all passing on c016211. Deployed (`make up-app`), database at 0025; Caddy restarted for its new headers (it is not recreated by the deploy). Live on the tailnet: a forged link answers 404 `link-closed`; `/s/` pages and `/api/v1/sign/*` carry `noindex` and `no-store`; `/countersign` signed out goes to log in and back; the handwriting fonts are served. The path from send to completed copy runs end to end in the API tests against Postgres (`test_completion.py`); the owner's click-through on the live site is the last check |

## 19. Review fixes

Findings from the review of the Phase 8 pull request, each fixed at its cause with a test that fails without the fix.

| # | Finding | Fix | Evidence |
|---|---|---|---|
| R1 | With no signer, the countersigners' turn never came: the envelope was written `sent`, and every countersigner check (routes, inbox, completion) needs `signed` | `signed` means every signer has signed, which holds from the start when there is none: the send writes the envelope `signed` when the countersigners go first (`envelopes/store.write_send`, from `Plan.first`) | `test_countersign.py::test_with_no_signer_the_countersigners_sign_at_once_and_the_envelope_completes` |
| R2 | Sign and submit did not wait for drafts: a value typed within the 0.8 s pause, or a save still on its way, could reach the server after the submit read the values | Before a submit the screen saves every waiting draft at once and waits for every save on its way; a field's saves run one after another so the last value given is the one kept; a refused save points the guide at its field and nothing is submitted (`SigningScreen.flushDrafts`) | `screen.test.tsx`: submits only once every draft is on the server |
| R3 | The link was exchanged as the page loaded, so a link-safety service that runs the page's script opened a session, recorded "opened" and sent an email code | The link page waits for the person's press of Review document before the exchange (§1.1.2) | `signing.test.tsx`: opens nothing until the person presses Review document |
| R4 | After the sender corrected an email address, the new address inherited the old one's minute between codes and its five an hour | A code row of an older link version is the old address's: the new address starts with no wait and its own hour (`codes.send_code`) | `test_code.py::test_a_corrected_email_ends_the_code_and_starts_its_own_limits` |
| R5 | The per-person limits (drafts; submit and decline) were counted by the recipient id in the path, before the request was checked: anyone with the id could spend the signer's allowance | Counted only after the request is checked as theirs, against the caller (`Signer.caller`: the browser session for a signer, the user for a countersigner) and the person (`limits.by_caller`); a request that is not theirs is refused by the session check and spends nothing | `test_limits.py::test_a_persons_allowance_is_spent_only_by_their_own_checked_requests` |
| R6 | A stored submit or decline answer was replayed before the caller was checked, under a scope of "anonymous" and the path: anyone with the recipient id and the key got the signer's answer | Who is asking (`service.identify`: the session's grant, or the countersigner's sign-in) is checked first; the key is scoped to that caller (`IdempotencyGuard.for_caller`) and a stored answer is replayed only to them; whether the envelope is open to them now (`service.may_act`) is checked for new work only, so a retried decline still gets its answer after it closed the envelope | `test_submit.py::test_a_stored_answer_is_replayed_only_to_the_caller_who_first_got_it`; `test_decline.py` replay |
| R7 | The done screen (who is still to sign, the countersigning company) was answered to a browser holding the link but not the email code; and the next step of a signed person was "done" before the code, against §1.1.7 | The next step puts the code first, then the done screen (`domain.next_step`); the done screen's answer requires the code and consent as the document does (`service.done` calls `require_ready`) | `test_code.py::test_after_signing_another_browser_asks_for_the_code_before_the_done_screen` |
| R8 | Changing the adopted signature did not take the envelope's lock: during a submit it could change the signature after the submit had read it, so the stored signature differed from the one its values and audit named | A change reads the person again under the envelope's lock that submit and decline take first (`service.locked`), so it applies wholly before a submit or is refused after it (`already-signed`) | `test_signatures.py::test_a_change_of_signature_waits_for_a_submit_under_way_and_then_is_refused` |
| R9 | Which field types are a place to sign was written five times (review's warning, sending's signing parties, signing's view, drafts, submit, drawing, the done screen's query), so review, send and signing could disagree on who is asked to sign | One definition, `review.values.SIGNING_PLACES`, beside the other field-type sets; every use imports it, the done screen's query binds it | review, envelopes and signing suites (282 passing) |
| R10 | The certificate read each person's signing event twice, each `LIMIT 1` with no order (a review note, not posted as a defect: there is one such event per person) | Read once with a lateral join, the first by its place on the envelope's chain | `test_completion.py` (the certificate names how each person was verified) |
| R11 | A review save of 2 000 fields grew slower as signing data grew: `envelope_values` and `signing_drafts` point at template fields with no index on `field_id`, so each deleted field scanned both tables (and `envelope_recipients` for each party, and for each mail cleared) | An index on each foreign key into rows the app deletes (migration 0030); a test reads every `DELETE FROM` in the source, follows cascades, and fails on any such key without an index | `tests/test_foreign_key_indexes.py`; the save's timing test passes in the full suite |
| R12 | A signature grew upward to 36 points without looking at the page: on a tight signature block (a firm's name on the line above) its frame and mark covered the agreement's text, on the screen and in the signed PDF | The room above each signature or initials place is read from the PDF at approval (`typesetting.marks`, kept in `placement_mark_tops`, measured for earlier versions by `signora measure-text-sizes`); the box grows only to just under the lowest word above it. One rule (`typesetting.mark_top`) gives the box the screen shows (`mark_top` on each place) and the one the PDF draws in | `typesetting/test_marks.py`, `review/test_text_sizes.py`, `rendering/test_draw.py` |

After the review fixes the full check passes (`make check` on its own test database): lint, types, 19 import contracts, 775 API tests, contract check, web lint and types, 346 web tests, build. Two tests that named the default test database now use the configured one, and the shared contract carries the certificate's font use.
