COMPOSE ?= docker compose
WAIT_ATTEMPTS ?= 30

.PHONY: up migrate wait-for-db down logs

up: migrate

	$(COMPOSE) up -d app

migrate:
	$(COMPOSE) up -d postgres
	$(MAKE) wait-for-db
	$(COMPOSE) run --rm --build --no-deps app uv run --no-dev alembic upgrade head

wait-for-db:
	@attempt=0; \
	until $(COMPOSE) exec -T postgres pg_isready -U virtual_company -d virtual_company >/dev/null 2>&1; do \
		attempt=$$((attempt + 1)); \
		if [ $$attempt -ge $(WAIT_ATTEMPTS) ]; then \
			echo "PostgreSQL did not become ready after $(WAIT_ATTEMPTS) attempts." >&2; \
			exit 1; \
		fi; \
		echo "Waiting for PostgreSQL..."; \
		sleep 1; \
	done

down:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f app
