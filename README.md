# Barkot Bar & Restaurant — Business Operations System

Internal operations and control system for Barkot Bar & Restaurant, covering sales, inventory, finance/balance and monthly payroll.

Primary users: Owner, Manager, Cashier, Barman. Currency: ETB. Business timezone: Africa/Addis_Ababa.

## Status

**Phase 0 — environment and design baseline. Structure only.** This repository currently contains no business logic, no database models, no API endpoints, no authentication, no UI and no deployment configuration.

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

`frontend/` and `backend/` never import from each other. They communicate only over the `/api/v1/` REST contract, and they are built, tested and deployed independently.

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
