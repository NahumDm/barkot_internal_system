# Barkot Management System — Backend

Django 5.2.x LTS + Django REST Framework 3.18.x. Modular monolith, one deployable. Runtime is
**Python 3.14** (spec §5 pins 3.13.x — see `docs/architecture/ADR/ADR-0002-python-runtime.md`).

## Layout

- `config/` — Django project settings, root URLconf, WSGI/ASGI entrypoints.
- `apps/<domain>/` — one Django app per business domain. Owns its own models, serializers, views, services and tests.
- `requirements/` — pinned dependency definitions (`base`, `dev`, `prod`) + resolved `requirements.lock`.
- `tests/` — cross-domain and system-level tests (`tests/integration/`).
- `manage.py` — standard Django management entrypoint.

## Setup (PowerShell / Windows)

The Postgres database runs in Docker; start it from the repository root:

```powershell
docker compose up -d db
```

Then, from this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements\dev.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

Health checks: <http://127.0.0.1:8000/health/live> (200) and <http://127.0.0.1:8000/health/ready>
(200 once the database is reachable — see `config/health.py`).

> `make`-based users can run `make dev-up` then `make dev-shell-api` / `make dev-shell-db`
> instead of the docker-compose command above.

## Verify (the CI gates)

```powershell
.\.venv\Scripts\ruff check .                       # lint
.\.venv\Scripts\ruff format --check .             # formatting
.\.venv\Scripts\mypy .                            # type check
.\.venv\Scripts\python.exe -m pytest             # tests (needs db container)
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run   # no model drift
.\.venv\Scripts\python.exe manage.py spectacular --file schema.yml --validate  # OpenAPI
```

## Database defaults

Defaults come from `DJANGO_DB_*` environment variables (see `.env.example` at the repository
root): name `barkot`, user `barkot`, password `barkot`, host `127.0.0.1`.

> This machine already runs a local PostgreSQL on port 5432, so the Docker dev database is
> published on `127.0.0.1:5433` (`docker compose up -d db`). For a local `runserver` against it,
> set `DJANGO_DB_PORT=5433` (in-container connections use the internal network and stay on 5432).
> Machines without a local PostgreSQL can restore the conventional `DJANGO_DB_PORT=5432`.

## Domain dependency rule

Dependencies flow inward toward business rules and data:

```
core  <-  everything (shared enums, base models, money/time utilities, errors)
accounts, users, products, audit  <-  core
sales  <-  products, inventory, finance, audit
inventory  <-  products, audit
finance  <-  sales, inventory, payroll
payroll  <-  users, finance, audit
reports  <-  all domains, read-only, never owns source truth
```

Views and controllers orchestrate use cases. Multi-step financial or inventory calculations belong in services, not in serializers (spec §8.2).

## API

Versioned REST + JSON under `/api/v1/`. Django session auth with secure HttpOnly cookies and CSRF for the web MVP (spec §9.1).

## Status

Phase 0A scaffold: 11 domain apps (`accounts, users, products, sales, inventory, finance, payroll,
reports, audit, integrations, core`) plus `/health/live` and `/health/ready`. No business models,
endpoints or auth yet.
