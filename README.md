# Barkot Bar & Restaurant — Business Operations System

Internal operations and control system for Barkot Bar & Restaurant, covering sales, inventory, finance/balance and monthly payroll.

Primary users: Owner, Manager, Cashier, Barman. Currency: ETB. Business timezone: Africa/Addis_Ababa.

## Status

**Phase 0A — structure bootstrap complete.** Repositories for both applications, toolchains,
health endpoints, Docker images, Nginx and CI are in place and verified green locally. There is
still no business logic, no database models, no API endpoints, no authentication and no real UI —
those land in Phase 0B and Phase 1.

Current phase status:

| Area | State |
| --- | --- |
| Backend (Django 5.2 LTS + DRF) | Scaffold + 11 domain apps, venv `backend/.venv`, locked `requirements.lock` |
| Frontend (Next.js 16 + React 19.3 + TS 5.9 + Tailwind 4) | Shell with all 17 §7.4 routes, sidebar, testing harness |
| Health endpoints | `/health/live` and `/health/ready` (L7+RDS, §8.3) |
| Docker / Nginx / Compose | Dev + prod compose, multi-target Dockerfiles, host Nginx config |
| CI | `.github/workflows/ci.yml` — the 7 §22.2 gates on both stacks |
| Docs | ADRs recorded — see `docs/architecture/ADR/` |

Architecture decisions (layout, Python 3.14) are recorded as **ADRs** in `docs/architecture/ADR/`.
The BARKOT-SAS-001 Word spec is author-maintained; deviations are noted in the ADRs for the next
(v1.1.0) spec revision.

## Getting started

Everything below is also available through the root `Makefile` (`make help`) for UNIX-like shells.
Windows without `make`: use the commands directly as shown.

1. **Database (local or CI):** only the database needs Docker for day-to-day work.
   `docker compose up -d db` then `docker compose exec db psql -U barkot` to poke around.
2. **Backend** (example PowerShell): `cd backend; python -m venv .venv; .\.venv\Scripts\pip`
   uses `; .\.venv\Scripts\python.exe` from then on. See [`backend/README.md`](backend/README.md).
3. **Frontend:** `cd frontend; npm ci; npm run dev` → http://localhost:3000 (redirects to
   `/dashboard`).
4. **All-in dev stack:** `docker compose up -d` (db + api + web with hot reload).

> The root `Makefile` is an orchestration convenience only. `make ci` runs the same gates as the
> CI pipeline. On Windows run `make` from a POSIX-style shell (Git Bash/WSL), or run each app's
> commands directly.

## Architecture at a glance

| Layer | Stack |
| --- | --- |
| Frontend | Next.js 16.x (App Router) + TypeScript 5.9 + React 19.3 + Tailwind CSS 4.x |
| Backend | Django 5.2.x LTS + Django REST Framework 3.18.x, modular monolith |
| Database | PostgreSQL 17.x, the single system of record |
| Web server | Nginx (TLS termination, `/` to web, `/api/v1/` to API) |
| Runtime | Docker Compose on one commercially permitted VPS |
| Async | Redis/Valkey + Celery — optional, added only when a real async workload exists |

Full detail: [`docs/architecture/`](docs/architecture/). Design contract: [`docs/ui-ux/`](docs/ui-ux/).

## Repository structure

```
barkot_internal_system/
├── frontend/          Next.js + TypeScript application
├── backend/           Django + DRF application
├── infrastructure/    Docker, Nginx and operational scripts
├── docs/              Architecture, API, UI/UX, business and runbook documentation
├── .github/workflows/ CI pipelines
├── docker-compose.yml
├── docker-compose.prod.yml
└── .env.example
```

## Frontend and backend are separate

`frontend/` and `backend/` never import from each other. They communicate only over the `/api/v1/` REST contract, and they are built, tested and deployed independently. The root `Makefile` orchestrates them for CI parity but is not required at runtime.

## Guiding rules

- PostgreSQL is the system of record. Dashboards and reports are views over transactions, never a second source of truth.
- Inventory and financial values are a ledger. Historical records are corrected with adjustments, never silently overwritten.
- Multi-step operations (complete sale, receive stock, complete stock count, approve payroll) are atomic and idempotent.
- Money is `Decimal`/`NUMERIC`, never floating point. Each transaction line persists the price actually used.
- Backend permissions are authoritative. Frontend visibility is presentation only.
- Corrections and sensitive operations are audited with actor, timestamp, entity, action and reason.
- Timestamps stored in UTC; daily and period reports calculated in Africa/Addis_Ababa.
- No secrets in Git.

## Conventions

- Branching: `main` (production-ready), `staging` (release candidate), `feature/*`.
- Commits are not yet governed by a documented convention — to be agreed before the first implementation commit.
