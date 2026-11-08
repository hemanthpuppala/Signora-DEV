# Signora

Multi-tenant agreement automation: upload an agreement once, let Signora detect its fields, approve them, and get it signed by any number of customers with a secure, minimal signing flow.

Design and decisions: [`docs/design/signora-platform.md`](docs/design/signora-platform.md).

## Quick start

Requirements: Linux or macOS, Docker with Compose v2, `curl`, Node.js 20.9+ with pnpm (or corepack). Everything else (uv, Python 3.12, all packages) is installed by the script.

```bash
git clone https://github.com/hemanthpuppala/Signora-DEV.git signora
cd signora
./install.sh
```

`install.sh`:
1. checks Docker/Compose; installs [uv](https://docs.astral.sh/uv/) 0.9.17 if missing (release archive verified against a pinned SHA-256) and refuses an older uv already on PATH;
2. creates `.env` from `.env.example` with generated secrets (mode 600; an existing `.env` is never overwritten) and checks required secrets are set;
3. creates `apps/api/.venv` from the lockfile (`uv sync --frozen`);
4. installs frontend packages (`pnpm install --frozen-lockfile` for `apps/web` and `packages/contracts`);
5. pulls and starts Postgres, Gotenberg (behind its gateway) and Mailpit, and waits until they are healthy.

Options: `--no-services` (skip Docker).

Then fill in the external credentials in `.env`: `AI_API_KEY`, the email settings below, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.

### Email

Account emails (sign-up links, password resets, invitations) go through one of three providers, chosen by
`EMAIL_PROVIDER` in `.env`; changing provider needs no code change.

| `EMAIL_PROVIDER` | Use | Also set |
|---|---|---|
| `mailpit` | Development: every email is captured, nothing leaves the machine. Read them at http://127.0.0.1:8025. Never allowed in production. | `EMAIL_FROM_ADDRESS` (any address) |
| `smtp` | Gmail: turn on 2-Step Verification, create an app password at https://myaccount.google.com/apppasswords | `SMTP_USERNAME` (the Gmail address), `SMTP_PASSWORD` (the 16-character app password), `EMAIL_FROM_ADDRESS` (the same Gmail address) |
| `sendgrid` | SendGrid's API (link tracking is switched off so sign-in links are never rewritten) | `SENDGRID_API_KEY` (Mail Send permission), `EMAIL_FROM_ADDRESS` (a verified sender) |

`EMAIL_DAILY_LIMIT` (default 450) holds mail back before Gmail's daily cap. A `@gmail.com` sender sent through
SendGrid may land in spam, because it cannot pass Gmail's domain authentication; Gmail SMTP does not have that
problem.

### Without uv

Pinned, hash-checked requirement files are exported from the lockfile:

```bash
cd apps/api
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt     # or requirements.txt for runtime only
pip install --no-deps -e .
```

Regenerate them after changing dependencies with `make requirements`.

## Running

### Development (code on the host, infrastructure in Docker)

```bash
make up        # Postgres, Gotenberg and Mailpit (inbox at http://127.0.0.1:8025)
make migrate   # apply database migrations
make api       # API with reload on 127.0.0.1:8100
make worker    # background worker
make web       # Next.js on 127.0.0.1:3200 (forwards /api to the API)
```

`/dev/ui` shows every design-system component (development only).

### Full stack (what the public URL serves)

```bash
make up-app    # builds images, runs migrations, starts api, worker, web and Caddy on 127.0.0.1:3100
```

Tailscale Funnel forwards `https://<host>.ts.net` to `127.0.0.1:3100`. `make down` stops everything (data volumes are kept).

| Service | Address | Purpose |
|---|---|---|
| Caddy 2.11.7 | `127.0.0.1:3100` | single entry point: `/api/*` → API, everything else → web; security headers; request ids; `/internal/*` blocked |
| api | internal | FastAPI (`signora api`) |
| worker | internal | background jobs (`signora worker`) |
| web | internal | Next.js standalone server |
| migrate | one-shot | `signora migrate` before api and worker start |
| Postgres 18.4 | `127.0.0.1:${POSTGRES_PORT}` (default 55432) | data and job queue |
| Gotenberg 8.40.0 | `127.0.0.1:${GOTENBERG_PORT}` (default 53000, via `gotenberg-gateway`) | DOCX → PDF (LibreOffice); no network egress |

`make ps`, `make logs`, `make help` for everything else.

## Quality gate

There is no hosted CI. Before merging, run:

```bash
make check     # ruff, mypy --strict, import boundaries, pytest (coverage gate), contract drift,
               # ESLint (incl. module boundaries), tsc, Vitest, next build
```

The API contract has one source of truth, the FastAPI app: `make contracts` regenerates `packages/contracts` from its OpenAPI document, and `make check` fails if the committed contract is out of date.

## Dependency policy

Only releases that have been public for at least two weeks are installed (supply-chain safety): `[tool.uv] exclude-newer` in `apps/api/pyproject.toml` for Python, `minimumReleaseAge` in `pnpm-workspace.yaml` for JavaScript, and exact tags for container images. Bump deliberately when upgrading. pnpm blocks package install scripts except those listed under `allowBuilds`. The installer pins uv itself to 0.9.17 with per-platform archive checksums; update `UV_VERSION` and the hashes in `install.sh` together.

Each service port is set once in `.env` (`POSTGRES_PORT`, `GOTENBERG_PORT`): Docker publishes it and the app connects to it.

## Licensing note

Signora uses **PyMuPDF** (`pymupdf`, `pymupdf4llm`) for PDF parsing, stamping and flattening. PyMuPDF is dual-licensed under **AGPL-3.0** or an **Artifex commercial license**. Since PyMuPDF 2.0 the former `pymupdf-layout` code ships inside `pymupdf` (the `pymupdf-layout` 2.0 package is an empty placeholder), so it is covered by the same declared license. This repository is public and AGPL-compatible. **A company selling or hosting Signora as a closed product must either buy an Artifex commercial license or replace PyMuPDF** with permissively licensed libraries (e.g. `pypdfium2` + `pdfplumber` + `pypdf`).

All other runtime dependencies are permissively licensed (MIT/BSD/Apache-2.0).
