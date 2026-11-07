COMPOSE := docker compose -f infra/compose.yaml --env-file .env

.PHONY: install requirements up down ps logs

install:       ## One-command setup (see install.sh --help)
	./install.sh

requirements:  ## Re-export pinned pip requirement files from uv.lock
	cd apps/api && uv lock --check && \
	uv export --frozen --no-dev --no-emit-project -o requirements.txt && \
	uv export --frozen --group dev --no-emit-project -o requirements-dev.txt

up:            ## Start infrastructure services and wait until healthy
	$(COMPOSE) up -d --wait --remove-orphans postgres gotenberg gotenberg-gateway

down:          ## Stop services (data volume kept)
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100
