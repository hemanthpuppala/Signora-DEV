COMPOSE := docker compose -f infra/compose.yaml --env-file .env

.PHONY: up down ps logs

up:            ## Start infrastructure services and wait until healthy
	$(COMPOSE) up -d --wait postgres gotenberg

down:          ## Stop services (data volume kept)
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100
