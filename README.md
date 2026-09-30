# Barkot Bar & Restaurant — Business Operations System

Internal operations and control system for Barkot Bar & Restaurant, covering sales, inventory, finance/balance and monthly payroll.

Primary users: Owner, Manager, Cashier, Barman. Currency: ETB. Business timezone: Africa/Addis_Ababa.

## Status

**Domain foundation complete; the API and UI are not.** The backend's models, service layer,
migrations, role matrix and tests are done for every domain. What is missing is everything that makes
them reachable: the REST API is not written and the frontend has no data layer. The backend is
currently exercisable only through the test suite.

**The build plan is [`docs/roadmap.md`](docs/roadmap.md).** Read that for what is next and why.

Current state:

| Area | State |
| --- | --- |
| Backend (Django 5.2 LTS + DRF) | 9 domain apps with models, 4 with service layers, 10 migrations applied |
| Tests | 156 passing — domain invariants, permission matrix, production config guards, error envelope, API base, pagination, endpoint contract rules |
| Static analysis | mypy clean (115 files), ruff clean |
| Authentication | Custom user, 4-role permission matrix, session/CSRF settings wired |
| **API** | **Versioned under `/api/v1/`, one error envelope for every failure, pagination with a hard cap, and an OpenAPI schema that documents `/api/v1/`. No business endpoints yet.** |
| **Frontend** | **Shell only. 24 files, no API client, no auth, 7 feature directories empty.** |
| `reports` app | `apps.py` only |
| Audit | `AuditLog.record()` called from services; no API to read it |
| **Contract suite** | **`tests/api/contract.py` — 5 rules every registered endpoint must satisfy, with declared exemptions. A new endpoint is checked automatically.** |
| Docker / Nginx / Compose | Dev + prod compose, multi-target Dockerfiles, host Nginx config |
| CI | `.github/workflows/ci.yml` — the 7 §22.2 gates on both stacks |
| Docs | ADRs 0001–0004, client decisions, roadmap |

### How this maps to spec §28

Spec §28 lays out seven phases as a horizontal, domain-by-domain sequence. The work so far was built
as one vertical slice instead, so §28 no longer describes the repository literally. The important
part:

**The backend work of spec Phases 1–4 is complete** — models, business rules and services for auth,
users, products, sales, inventory, finance and payroll. What remains for those phases is the API, the
frontend, and hardening. Recorded in
[ADR-0004](docs/architecture/ADR/ADR-0004-phase-0b-vertical-slice.md).

| Spec §28 phase | State |
| --- | --- |
| 0 — Environment + design baseline | Complete |
| 1 — Auth + users + products | Domain layer complete; API and UI outstanding |
| 2 — Sales + inventory | Domain layer complete; API and UI outstanding |
| 3 — Finance | Domain layer complete; API and UI outstanding |
| 4 — Payroll | Domain layer complete; API and UI outstanding |
| 5 — Hardening | Not started |
| 6 — Optional integrations | Not started; blocked on open client questions |

Architecture decisions are recorded as **ADRs** in `docs/architecture/ADR/`. The BARKOT-SAS-001 Word
spec is author-maintained; deviations are noted in the ADRs for the next (v1.1.0) spec revision.

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
