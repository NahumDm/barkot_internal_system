# Barkot — root task runner (orchestration only)
#
# This Makefile is a convenience for UNIX-like shells and matches the CI
# pipeline step-for-step so a green `make ci` locally predicts a green run.
# It is NOT a runtime dependency. Windows without `make`: run the equivalent
# commands from each app README (PowerShell) and use `docker compose`,
# e.g. `docker compose up -d db`.

PY        ?= .venv/bin/python
PIP       ?= .venv/bin/pip
NPM       ?= npm
COMPOSE   ?= docker compose

.PHONY: help install install-backend install-frontend \
        dev-up dev-down dev-logs dev-shell-api dev-shell-db \
        lint lint-backend lint-frontend \
        format format-check \
        typecheck-backend typecheck-frontend \
        test test-backend test-frontend test-e2e \
        check-migrations openapi build ci clean

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend ## Install both toolchains

install-backend: ## Create backend .venv and install dev requirements
	cd backend && python3 -m venv .venv && $(PIP) install -r requirements/dev.txt

install-frontend: ## Install frontend dependencies (npm ci from lockfile)
	cd frontend && $(NPM) ci

dev-up: ## Start dev stack (db + api + web) via Docker Compose
	$(COMPOSE) up -d

dev-down: ## Stop dev stack
	$(COMPOSE) down

dev-logs: ## Tail dev stack logs
	$(COMPOSE) logs -f --tail=100

dev-shell-api: ## Shell into the api container
	$(COMPOSE) exec api sh

dev-shell-db: ## Open psql as the barkot user
	$(COMPOSE) exec db psql -U $$DJANGO_DB_USER

lint: lint-backend lint-frontend ## Lint both stacks

lint-backend: ## ruff check
	cd backend && .venv/bin/ruff check .

lint-frontend: ## eslint
	cd frontend && $(NPM) run lint

format: ## Apply formatters to both stacks
	cd backend && .venv/bin/ruff format .
	cd frontend && $(NPM) run format

format-check: ## Verify formatting on both stacks
	cd backend && .venv/bin/ruff format --check .
	cd frontend && $(NPM) run format:check

typecheck-backend: ## mypy
	cd backend && .venv/bin/mypy .

typecheck-frontend: ## tsc --noEmit
	cd frontend && $(NPM) run typecheck

test: test-backend test-frontend ## Run unit tests on both stacks

test-backend: ## pytest (requires the db container)
	cd backend && .venv/bin/pytest

test-frontend: ## vitest
	cd frontend && $(NPM) test

test-e2e: ## Playwright smoke (builds + runs standalone server)
	cd frontend && $(NPM) run test:e2e

check-migrations: ## No model changes should surprise CI
	cd backend && .venv/bin/python manage.py makemigrations --check --dry-run

openapi: ## Generate and validate the OpenAPI schema
	cd backend && .venv/bin/python manage.py spectacular --file schema.yml --validate

build: ## Build dev Docker images
	$(COMPOSE) build

ci: lint format-check typecheck-backend typecheck-frontend \
    test-backend test-frontend check-migrations openapi ## Local CI parity

clean: ## Remove generated artifacts
	cd backend && rm -rf .venv
	cd frontend && rm -rf node_modules .next coverage playwright-report test-results