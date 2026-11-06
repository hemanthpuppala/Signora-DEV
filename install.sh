#!/usr/bin/env bash
# Signora one-command setup: ./install.sh
#
# Installs everything needed to run Signora locally:
#   1. checks prerequisites (Docker + Compose, curl, Python via uv)
#   2. installs uv if missing (official installer)
#   3. creates .env from .env.example with generated secrets (never overwrites an existing .env)
#   4. creates the backend virtualenv (apps/api/.venv) from the lockfile
#   5. installs frontend packages when the web app is present
#   6. pulls and starts infrastructure services (Postgres, Gotenberg)
#
# Options:
#   --no-services   skip pulling/starting Docker services
#   --with-eval     also install the private detection-eval tooling group
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$ROOT/apps/api"
WEB_DIR="$ROOT/apps/web"
START_SERVICES=1
WITH_EVAL=0

for arg in "$@"; do
  case "$arg" in
    --no-services) START_SERVICES=0 ;;
    --with-eval)   WITH_EVAL=1 ;;
    -h|--help)     sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ok\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1. Prerequisites -------------------------------------------------------
info "Checking prerequisites"
command -v curl >/dev/null 2>&1 || fail "curl is required"
if [[ $START_SERVICES -eq 1 ]]; then
  command -v docker >/dev/null 2>&1 || fail "Docker is required (https://docs.docker.com/engine/install/)"
  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"
  docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable (is it running, and is your user in the docker group?)"
  ok "docker $(docker compose version --short)"
fi

# --- 2. uv (Python package manager; also provisions Python 3.12 if missing) --
if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv (https://docs.astral.sh/uv/)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv installation failed"
fi
ok "$(uv --version)"

# --- 3. Environment file -----------------------------------------------------
if [[ -f "$ROOT/.env" ]]; then
  ok ".env already exists (left unchanged)"
else
  info "Creating .env from .env.example with generated secrets"
  uv run --no-project --python 3.12 python - "$ROOT/.env.example" "$ROOT/.env" <<'PY'
import re, secrets, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
generated = {"SECRET_KEY": secrets.token_urlsafe(64), "POSTGRES_PASSWORD": secrets.token_urlsafe(24)}
for key, value in generated.items():
    text = re.sub(rf"^{key}=[^\S\n]*(#.*)?$", f"{key}={value}", text, count=1, flags=re.M)
open(dst, "w", encoding="utf-8").write(text)
PY
  chmod 600 "$ROOT/.env"
  ok ".env created — fill in AI_API_KEY, SMTP_*, EMAIL_FROM_ADDRESS, STRIPE_* before running the app"
fi

# --- 4. Backend virtualenv -----------------------------------------------------
info "Installing backend dependencies into apps/api/.venv (from uv.lock)"
groups=(--group dev)
[[ $WITH_EVAL -eq 1 ]] && groups+=(--group eval)
(cd "$API_DIR" && uv sync --frozen "${groups[@]}")
ok "backend: $("$API_DIR/.venv/bin/python" --version), $("$API_DIR/.venv/bin/python" -c 'import fastapi, pymupdf; print(f"fastapi {fastapi.__version__}, pymupdf {pymupdf.VersionBind}")')"

# --- 5. Frontend packages --------------------------------------------------------
if [[ -f "$WEB_DIR/package.json" ]]; then
  info "Installing frontend dependencies"
  command -v node >/dev/null 2>&1 || fail "Node.js 20+ is required for the web app (https://nodejs.org/)"
  node -e 'process.exit(parseInt(process.versions.node) >= 20 ? 0 : 1)' || fail "Node.js 20+ is required (found $(node --version))"
  command -v pnpm >/dev/null 2>&1 || { corepack enable >/dev/null 2>&1 || fail "pnpm missing; run: npm install -g pnpm"; }
  (cd "$ROOT" && pnpm install --frozen-lockfile)
  ok "frontend dependencies installed"
else
  ok "web app not present yet — skipping frontend install"
fi

# --- 6. Infrastructure services --------------------------------------------------
if [[ $START_SERVICES -eq 1 ]]; then
  info "Pulling and starting Postgres and Gotenberg"
  docker compose -f "$ROOT/infra/compose.yaml" --env-file "$ROOT/.env" pull postgres gotenberg
  docker compose -f "$ROOT/infra/compose.yaml" --env-file "$ROOT/.env" up -d --wait postgres gotenberg
  ok "services healthy"
fi

info "Done. Activate the backend environment with: source apps/api/.venv/bin/activate"
