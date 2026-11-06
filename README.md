# Signora

Multi-tenant agreement automation: upload an agreement once, let Signora detect its fields, approve them, and get it signed by any number of customers with a secure, minimal signing flow.

Design and decisions: [`docs/design/signora-platform.md`](docs/design/signora-platform.md).

## Quick start

Requirements: Linux or macOS, Docker with Compose v2, `curl`. Everything else (uv, Python 3.12, all packages) is installed by the script.

```bash
git clone https://github.com/hemanthpuppala/Signora-DEV.git signora
cd signora
./install.sh
```

`install.sh`:
1. checks Docker/Compose and installs [uv](https://docs.astral.sh/uv/) if missing;
2. creates `.env` from `.env.example` with generated secrets (an existing `.env` is never overwritten);
3. creates `apps/api/.venv` from the lockfile (`uv sync --frozen`);
4. installs frontend packages once the web app exists;
5. pulls and starts Postgres and Gotenberg and waits until they are healthy.

Options: `--no-services` (skip Docker), `--with-eval` (include internal eval tooling).

Then fill in the external credentials in `.env`: `AI_API_KEY`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM_ADDRESS`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.

### Without uv

Pinned, hash-checked requirement files are exported from the lockfile:

```bash
cd apps/api
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt     # or requirements.txt for runtime only
pip install --no-deps -e .
```

Regenerate them after changing dependencies with `make requirements`.

## Services

| Service | Host address (local only) | Purpose |
|---|---|---|
| Postgres 18.4 | `127.0.0.1:55432` | data, job queue, outbox |
| Gotenberg 8.40.0 | `127.0.0.1:53000` | DOCX → PDF (LibreOffice) |

`make up`, `make down`, `make ps`, `make logs`.

## Dependency policy

`[tool.uv] exclude-newer` in `apps/api/pyproject.toml` only allows package releases that have been public for at least two weeks (supply-chain safety). Bump the date deliberately when upgrading.

## Licensing note

Signora uses **PyMuPDF** (`pymupdf`, `pymupdf4llm`) for PDF parsing, stamping and flattening. PyMuPDF is dual-licensed under **AGPL-3.0** or an **Artifex commercial license**. Since PyMuPDF 2.0 the former `pymupdf-layout` code ships inside `pymupdf` (the `pymupdf-layout` 2.0 package is an empty placeholder), so it is covered by the same declared license. This repository is public and AGPL-compatible. **A company selling or hosting Signora as a closed product must either buy an Artifex commercial license or replace PyMuPDF** with permissively licensed libraries (e.g. `pypdfium2` + `pdfplumber` + `pypdf`).

All other runtime dependencies are permissively licensed (MIT/BSD/Apache-2.0).
