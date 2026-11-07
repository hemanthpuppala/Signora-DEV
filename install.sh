#!/usr/bin/env bash
# Signora one-command setup: ./install.sh
#
# Installs everything needed to run Signora locally:
#   1. checks prerequisites (Docker + Compose, curl)
#   2. installs a pinned uv if missing (uv also provisions Python 3.12)
#   3. creates .env from .env.example with generated secrets (never overwrites an existing .env)
#      and checks that required secrets are set
#   4. creates the backend virtualenv (apps/api/.venv) from the lockfile, with dev tooling
#   5. installs frontend packages once the pnpm workspace exists
#   6. pulls and starts infrastructure services (Postgres, Gotenberg + gateway)
#
# Options:
#   --no-services   skip pulling/starting Docker services
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$ROOT/apps/api"
UV_VERSION="0.9.17"     # pinned installer, consistent with the dependency age policy in README
START_SERVICES=1

for arg in "$@"; do
  case "$arg" in
    --no-services) START_SERVICES=0 ;;
    -h|--help)     awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
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
  ok "docker compose $(docker compose version --short)"
fi

# --- 2. uv (Python package manager; also provisions Python 3.12 if missing) --
# The official installer honours UV_INSTALL_DIR, then XDG_BIN_HOME, then $XDG_DATA_HOME/../bin,
# then ~/.local/bin. Put all of them on PATH so an existing or fresh install is found either way.
for dir in "${UV_INSTALL_DIR:-}" "${XDG_BIN_HOME:-}" "${XDG_DATA_HOME:+$XDG_DATA_HOME/../bin}" "$HOME/.local/bin"; do
  [[ -n "$dir" ]] && PATH="$dir:$PATH"
done
export PATH

# SHA-256 of the official uv $UV_VERSION release archives (github.com/astral-sh/uv/releases).
uv_archive_sha256() {
  case "$1" in
    x86_64-unknown-linux-gnu)  echo 0114d54f9aafd07516cf1cadfe72afa970f5fd293fbe82dd924b8a7b42c984d8 ;;
    aarch64-unknown-linux-gnu) echo e9eba97b7169e47fd3c926e409f0b714820f0befc23b3ae062780586a793e4cc ;;
    x86_64-apple-darwin)       echo 249e7fb18d45c06ba283c48f0a8e586ecc5fbb9e8dad0923c4169a7c4db815b2 ;;
    aarch64-apple-darwin)      echo a1e1464aa1d04d5e5fa700aa2f2e10397d1114e835dbd56be25ba65c9a31bd99 ;;
  esac
}

# Downloads the pinned release archive and verifies it before installing. (The uv install
# script itself carries no checksums, so we do not pipe it to sh.)
install_uv() {
  local arch os target expected dest tmp actual
  case "$(uname -m)" in x86_64|amd64) arch=x86_64 ;; arm64|aarch64) arch=aarch64 ;; *) arch="" ;; esac
  case "$(uname -s)" in Linux) os=unknown-linux-gnu ;; Darwin) os=apple-darwin ;; *) os="" ;; esac
  target="$arch-$os"
  expected="$(uv_archive_sha256 "$target")"
  [[ -n "$arch" && -n "$os" && -n "$expected" ]] || fail "no pinned uv build for $(uname -s)/$(uname -m); install uv $UV_VERSION manually (https://docs.astral.sh/uv/) and re-run"
  dest="${UV_INSTALL_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  info "Installing uv $UV_VERSION ($target) into $dest"
  curl -fLsS "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$target.tar.gz" -o "$tmp/uv.tar.gz" \
    || fail "could not download uv $UV_VERSION"
  if command -v sha256sum >/dev/null 2>&1; then actual="$(sha256sum "$tmp/uv.tar.gz" | awk '{print $1}')"
  else actual="$(shasum -a 256 "$tmp/uv.tar.gz" | awk '{print $1}')"; fi
  [[ "$actual" == "$expected" ]] || fail "uv archive checksum mismatch (expected $expected, got $actual); not installing"
  tar -xzf "$tmp/uv.tar.gz" -C "$tmp"
  mkdir -p "$dest"
  install -m 0755 "$tmp/uv-$target/uv" "$tmp/uv-$target/uvx" "$dest/"
  hash -r
}

version_at_least() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]; }

if command -v uv >/dev/null 2>&1; then
  current="$(uv --version | awk '{print $2}')"
  version_at_least "$current" "$UV_VERSION" \
    || fail "uv $current is older than the required $UV_VERSION; run 'uv self update $UV_VERSION' (or remove it so this script installs the pinned version) and re-run"
else
  install_uv
  command -v uv >/dev/null 2>&1 || fail "uv was installed but is not on PATH; add its install directory to PATH and re-run"
fi
ok "$(uv --version)"

# --- 3. Environment file -----------------------------------------------------
if [[ -f "$ROOT/.env" ]]; then
  ok ".env already exists (left unchanged)"
else
  info "Creating .env from .env.example with generated secrets"
  # Written under umask 077 so the file is never readable by other users, even briefly.
  (
    umask 077
    uv run --no-project --python 3.12 python - "$ROOT/.env.example" "$ROOT/.env" <<'PY'
import re, secrets, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
generated = {"SECRET_KEY": secrets.token_urlsafe(64), "POSTGRES_PASSWORD": secrets.token_urlsafe(24)}
for key, value in generated.items():
    text, n = re.subn(rf"^{key}=[^\S\n]*(#.*)?$", f"{key}={value}", text, count=1, flags=re.M)
    if n != 1:
        sys.exit(f"{key} placeholder not found in {src}")
open(dst, "w", encoding="utf-8").write(text)
PY
  )
  ok ".env created (mode 600) — fill in AI_API_KEY, SMTP_*, EMAIL_FROM_ADDRESS, STRIPE_* before running the app"
fi
# Required secrets must be non-empty, whether .env was just generated or already existed.
for key in SECRET_KEY POSTGRES_PASSWORD; do
  value="$(sed -n "s/^${key}=\([^#[:space:]]*\).*/\1/p" "$ROOT/.env" | head -n1)"
  [[ -n "$value" ]] || fail "$key is empty in .env; set it (python3 -c 'import secrets;print(secrets.token_urlsafe(48))') and re-run"
done
ok "required secrets present"

# --- 4. Backend virtualenv -----------------------------------------------------
info "Installing backend dependencies into apps/api/.venv (from uv.lock)"
(cd "$API_DIR" && uv sync --frozen)
ok "backend: $("$API_DIR/.venv/bin/python" --version), $("$API_DIR/.venv/bin/python" -c 'import fastapi, pymupdf; print(f"fastapi {fastapi.__version__}, pymupdf {pymupdf.VersionBind}")')"

# --- 5. Frontend packages --------------------------------------------------------
# The frontend is a pnpm workspace rooted at the repository root (apps/web, packages/*).
if [[ -f "$ROOT/pnpm-workspace.yaml" ]]; then
  info "Installing frontend dependencies (pnpm workspace)"
  command -v node >/dev/null 2>&1 || fail "Node.js 20+ is required for the web app (https://nodejs.org/)"
  node -e 'process.exit(parseInt(process.versions.node) >= 20 ? 0 : 1)' || fail "Node.js 20+ is required (found $(node --version))"
  if ! command -v pnpm >/dev/null 2>&1; then
    # Corepack can provide pnpm without root when shims go to a user directory, and must not prompt.
    # The shim directory must exist (corepack does not create it); it is already on PATH (step 2).
    if command -v corepack >/dev/null 2>&1 && mkdir -p "$HOME/.local/bin" && \
       COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack enable --install-directory "$HOME/.local/bin" pnpm >/dev/null 2>&1 && \
       COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm --version >/dev/null 2>&1; then
      ok "pnpm enabled via corepack"
    else
      fail "pnpm is required: install it with 'npm install -g pnpm' (or see https://pnpm.io/installation) and re-run"
    fi
  fi
  (cd "$ROOT" && COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm install --frozen-lockfile)
  ok "frontend dependencies installed"
else
  ok "pnpm workspace not present yet — skipping frontend install"
fi

# --- 6. Infrastructure services --------------------------------------------------
if [[ $START_SERVICES -eq 1 ]]; then
  info "Pulling and starting Postgres and Gotenberg"
  compose=(docker compose -f "$ROOT/infra/compose.yaml" --env-file "$ROOT/.env")
  "${compose[@]}" pull postgres gotenberg gotenberg-gateway
  "${compose[@]}" up -d --wait --remove-orphans postgres gotenberg gotenberg-gateway
  ok "services healthy"
fi

info "Done. Activate the backend environment with: source apps/api/.venv/bin/activate"
