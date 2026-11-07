COMPOSE := docker compose -f infra/compose.yaml --env-file .env
API := apps/api
UV := cd $(API) && uv run --frozen
API_DEV_PORT ?= 8100

.PHONY: help install requirements up down ps logs \
        migrate api worker web \
        web-lint web-typecheck web-test web-build \
        contracts contracts-check format lint typecheck imports test check

help:          ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t 16

# --- setup -------------------------------------------------------------------------------------

install:       ## One-command setup (see install.sh --help)
	./install.sh

requirements:  ## Re-export pinned pip requirement files from uv.lock
	cd $(API) && uv lock --check && \
	uv export --frozen --no-dev --no-emit-project -o requirements.txt && \
	uv export --frozen --group dev --no-emit-project -o requirements-dev.txt

# --- infrastructure ----------------------------------------------------------------------------

up:            ## Start infrastructure services and wait until healthy
	$(COMPOSE) up -d --wait --remove-orphans postgres gotenberg gotenberg-gateway

down:          ## Stop services (data volume kept)
	$(COMPOSE) down

ps:            ## Show service status
	$(COMPOSE) ps

logs:          ## Follow service logs
	$(COMPOSE) logs -f --tail=100

# --- run on the host (development) -------------------------------------------------------------

migrate:       ## Apply database migrations
	$(UV) signora migrate

api:           ## Run the API with reload on API_DEV_PORT (default 8100)
	$(UV) signora api --reload --port $(API_DEV_PORT)

worker:        ## Run the background worker
	$(UV) signora worker

web:           ## Run the web app (next dev) on WEB_DEV_PORT (default 3200); /api goes to API_DEV_PORT
	API_DEV_PORT=$(API_DEV_PORT) pnpm --filter web dev

# --- API contract (single source of truth: the FastAPI app) -----------------------------------

contracts:     ## Regenerate packages/contracts from the API's OpenAPI document
	$(UV) signora openapi --output ../../packages/contracts/openapi.json
	pnpm --filter @signora/contracts generate
	pnpm --filter @signora/contracts typecheck

contracts-check: contracts  ## Fail if the committed contract differs from the API
	@scripts/check-clean.sh packages/contracts "run 'make contracts' and commit the result"

# --- quality gate (run before every merge; there is no hosted CI) ------------------------------

format:        ## Format and auto-fix Python code
	$(UV) ruff format src tests
	$(UV) ruff check --fix src tests

lint:          ## Check formatting and lint rules
	$(UV) ruff format --check src tests
	$(UV) ruff check src tests

typecheck:     ## Strict type checking
	$(UV) mypy src tests

imports:       ## Module boundary contracts
	$(UV) lint-imports

test:          ## Tests with coverage gate (>= 85% for kernel and audit); needs `make up`
	$(UV) pytest --cov=signora.kernel --cov=signora.modules.audit --cov-fail-under=85

web-lint:      ## ESLint, including frontend module boundaries
	pnpm --filter web lint

web-typecheck: ## Strict TypeScript
	pnpm --filter web typecheck

web-test:      ## Frontend unit tests (Vitest)
	pnpm --filter web test

web-build:     ## Production build of the web app
	pnpm --filter web build

check: lint typecheck imports test contracts-check web-lint web-typecheck web-test web-build  ## Everything that must pass before a merge
	@echo "make check: all gates passed"
