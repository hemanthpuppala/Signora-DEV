# Signora — submission

**Use it:** https://hemanth.tail50655e.ts.net
**Code:** https://github.com/hemanthpuppala/Signora-DEV (public)

## What I built

Signora gets a firm's client agreement signed on every file without anyone preparing it by hand.

A firm uploads its agreement once, as a PDF or Word file, even one Signora has never seen. AI reads the
agreement and finds every place to fill or sign and who fills each one: the client, the firm, or the
sender before sending. A person at the firm checks that proposal on the page, corrects what is wrong, and
approves it as a **template**. From then on, opening a new file takes one step. The sender types that
client's name and email (and anything the firm fills in, like a matter number), and Signora emails the
client a link. The client proves who they are with a code sent to their email, agrees to sign
electronically, fills in their details, signs and submits, all on any phone or computer. The firm
countersigns from its inbox. Signora then makes the signed PDF and a **certificate of completion** and
emails both to everyone.

It is built as a product a firm could buy, not a tool for one firm. Every company that signs up gets its
own isolated workspace, with departments, people, roles and its own templates. Astra AI is the first
customer, and the next firm signs up the same way.

### Trying it as Astra AI with the MIND agreement

1. **Sign up** with your email. Confirm the email, then name the company (your website is optional; it
   adds your logo to the header).
2. **Create a department**, for example "Client intake".
3. **Upload the agreement** on the department's Templates tab. Detection takes about half a minute.
4. **Review:** each field Signora found is listed and outlined on the page, with who fills it. Anything
   it was unsure of is listed under *Things to check*: confirm it with **Looks right** or fix it. Then
   **Approve**.
5. **New envelope:** choose the template and enter the client's name and email (use an address you can
   read). Fill in anything the firm completes before sending. Choose who countersigns for the firm. Send.
6. **As the client:** open the email, enter the code you are sent, agree to sign electronically, fill in
   the fields, sign and submit.
7. **As the firm:** open *To countersign*, sign. Everyone receives the signed PDF and the certificate by
   email. Both can also be downloaded from the envelope's page.

I ran this path end to end on the live URL with an agreement written for the test and never shown to
the system before. It took about half a minute from upload to fields found, and completed within seconds
of the countersignature.

## Features included, and why

**Agreements the system has never seen.** Since the MIND agreement isn't shared in advance, nothing is
built around a known layout.
- **AI detection** finds the blanks, signature lines, initials, dates, checkboxes and choices, groups
  them into fields, decides who fills each, and gives each a type (name, email, date, address, tax id and
  so on).
- **Word files** are converted to PDF.
- **Scanned agreements** (pages that are pictures) are read by the AI from the page image.
- **A PDF's own form fields** are used as their author drew them.
- **Signature and initials boxes** grow into the free space above their line, never over the
  agreement's text.

**A human review gate before anything is sent.** AI can be wrong, and a wrong field on a legal agreement
is expensive. Nothing can be sent until a person approves the template.
- Review shows every field on the page and in a list, grouped by who fills it.
- Fields the AI was unsure of are named in *Things to check*, with **Show me**, **Looks right** and
  **Next**. Approving accepts whatever is left, and says so.
- Fields can be edited, moved, resized, added and removed, with undo. Conditions (a field asked only when
  an option is chosen) are supported.
- Approval freezes the template as a version. Every send records exactly which version it used, and a
  later edit becomes a new version.

**Sending that asks only what the agreement needs.** The firm's goal is speed on every file.
- The send form is built from the template: only the fields the firm fills before sending, and the
  people.
- The client's own name and email are filled in where the agreement asks for them.
- Dates are written in each blank the way that agreement writes them (day-first, month names, "20__").
- **Bulk send:** one template to many clients from a spreadsheet, each row its own envelope.
- The sender can follow each envelope (opened, viewed, signed), remind, correct an email address, copy
  the signing link, send again after a decline, or cancel.

**Signing a client can do on a phone without help.**
- An emailed link and a one-time **email code** prove the signer controls the address the firm used.
- An **electronic-signature consent** disclosure is shown before signing (the ESIGN Act and UETA
  practice).
- A guided path walks through the fields: *Start*, *Next*, *Complete*.
- Typed signatures (three handwriting styles) or drawn ones; initials; **Apply to all**.
- The client may **decline** with a reason, which stops the envelope and tells the sender why.
- The firm **countersigns** while signed in, from a *To countersign* inbox. A countersigner's adopted
  signature is saved for the next time.

**Evidence that holds up.**
- **The signed PDF** is flattened (no editable fields, links or scripts left) and carries the envelope
  ID on every page.
- **The certificate of completion** lists each person:
  - how they were verified;
  - their signature with its fingerprint ID;
  - their IP address;
  - when they were sent, viewed and signed;
  - the disclosure they accepted.

  It also carries the SHA-256 fingerprints of the signed document.
- **An append-only, hash-chained audit trail** records every action (sent, opened, verified, consented,
  signed, declined, completed).

**Ready for many firms (the client's "sell it to every company in our industry").**
- Multi-tenant workspaces, strictly isolated.
- Departments with their own templates, envelopes and countersigners.
- Roles (owner, editor, viewer) with per-department access.
- Invitations and the company's logo in its header.
- Search across templates, envelopes and countersigning, forgiving typos, best match first. A dot marks
  a department with templates waiting for approval.
- Mail is sent through a real provider: Gmail SMTP here, SendGrid supported by configuration. Every email
  carries the Signora logo, and Gmail's apps keep it legible.

**Security basics a buyer will ask about.**
- Separate signer and console sessions, with CSRF protection.
- Rate limits on links, codes, submits and declines.
- Signing links never in logs or `Referer`; signing pages not indexed or cached.
- Idempotent submits, so a double click can't sign twice.
- Database constraints that freeze an approved template and a signed signature.

## Features deliberately left out, and why

- **Automatic reminder and expiry emails.** Each envelope has an expiry date, which is enforced: a link
  past it no longer opens. The sender can remind at any time. Scheduled reminders and expiry emails are a
  background job I didn't build within the week; I spent the time on getting the agreement right and
  signed.
- **Removing personal data before the AI reads an agreement.** Agreements are sent to the AI provider
  (OpenAI) to find their fields. For a firm with stricter privacy needs, the next step is redacting
  personal details first (for example with Microsoft Presidio) or using a provider under a data
  agreement. A template is usually blank, so little personal data reaches the AI today.
- **Advanced and qualified electronic signatures** (a certificate-based digital seal on the PDF, trusted
  timestamps). Simple electronic signatures with a strong audit trail are what US professional-services
  firms use for client agreements. A cryptographic seal adds cost and setup each firm would need.
- **Single sign-on, billing and subscriptions.** A firm can sign up and use the product. Selling to many
  firms would need SSO (SAML/OIDC) and billing, but neither changes whether an agreement gets signed.
- **Integrations** (case-management, CRM and document systems, webhooks). Valuable for "every file"
  automation at scale, but each depends on which system a firm uses.
- **In-person signing, signing in another language, and mobile apps.** The web app works on phones, which
  covers clients signing remotely.
- **Payment collection and file attachments from the signer.** Not part of getting an engagement
  agreement signed.

## Decisions and assumptions

- **"File" means one envelope:** one client, one job, one agreement sent and signed. The firm's template
  is reused for every file.
- **The agreement is unseen, so the AI proposes and a person approves.** I assumed the firm would rather
  spend a minute checking a template once than have every client receive a wrongly prepared agreement.
- **The client proves who they are by an email code** (on by default, can be switched off per send). The
  firm's countersigner is signed in, which is their proof.
- **The firm countersigns after every client has signed,** so the firm signs what the client agreed to.
- **Only test data:** every name, email and company used in testing is invented.
- **Hosting:** the service runs on one machine and is published through Tailscale Funnel. That is enough
  for evaluation. A firm's production deployment would run on a cloud host with managed Postgres and
  backups; the app is containerised for that.
- **Known limits:**
  - Detection can miss a checkbox written only as text ("[ ]"); the reviewer can add it in a click.
  - The first time an email's logo is loaded it is fetched from this host, so it can take a moment.

## Tools used

- **Built with Claude Code (Anthropic's Claude)** for design, implementation, tests and review.
- **Detection:** the OpenAI API (`gpt-6-luna`).
- **API:** Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL (with `pg_trgm` for search).
- **Web:** Next.js (React, TypeScript).
- **PDF and documents:**
  - PyMuPDF to read, draw and flatten PDFs;
  - Gotenberg (LibreOffice) to convert Word files to PDF;
  - pdf.js to show PDFs in the browser.
- **Email:** Gmail SMTP in production, Mailpit in development.
- **Company logos:** logo.dev.
- **Domains:** the Public Suffix List via `tldextract`.
- **Hosting and build:** Docker Compose, Caddy, Tailscale Funnel.
- **Fonts:** Great Vibes, Allura and Sacramento (SIL Open Font License) for typed signatures; Liberation
  fonts for documents.
