COMPOSE ?= docker compose
PNPM ?= corepack pnpm
WAIT_ATTEMPTS ?= 30

.PHONY: start up backend-up migrate wait-for-db down logs build check \
	test lint backend-test backend-lint frontend-install frontend-dev \
	frontend-build frontend-test frontend-lint frontend-format \
	frontend-format-check frontend-e2e-install frontend-e2e

start: up

up: migrate
	$(COMPOSE) up -d --build app frontend

backend-up: migrate
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
	$(COMPOSE) logs -f app frontend

build:
	$(COMPOSE) build app frontend

backend-test:
	uv run pytest

backend-lint:
	uv run ruff check .

frontend-install:
	cd frontend && $(PNPM) install

frontend-dev:
	cd frontend && $(PNPM) dev

frontend-build:
	cd frontend && $(PNPM) build

frontend-test:
	cd frontend && $(PNPM) test:run

frontend-lint:
	cd frontend && $(PNPM) lint

frontend-format:
	cd frontend && $(PNPM) format

frontend-format-check:
	cd frontend && $(PNPM) format:check

frontend-e2e-install:
	cd frontend && $(PNPM) exec playwright install chromium

frontend-e2e:
	cd frontend && $(PNPM) test:e2e

test: backend-test frontend-test

lint: backend-lint frontend-lint

check: lint frontend-format-check test frontend-build
