# Barkot Bar & Restaurant — Business Operations System

**Barkot** is the internal operations and control system for Barkot Bar & Restaurant (Addis Ababa).
It runs the four business flows that keep the bar accountable day to day: **point of sale (sales)**,
**inventory (stock control)**, **finance (balance and expenses)**, and **monthly payroll** — all behind
role-based access for the four positions that use it: **Owner, Manager, Cashier, and Barman**.

Currency: **ETB** (Ethiopian Birr). Business timezone: **Africa/Addis_Ababa**. Times are stored in UTC.

---

## Table of contents

1. [Status](#status)
2. [Architecture](#architecture)
3. [Authentication and authorization](#authentication-and-authorization)
4. [Security](#security)
5. [Domain and database design](#domain-and-database-design)
6. [API design](#api-design)
7. [Testing and CI](#testing-and-ci)
8. [Deployment and operations](#deployment-and-operations)
9. [Observability](#observability)
10. [Engineering notes and major decisions](#engineering-notes-and-major-decisions)
11. [Documentation](#documentation)
12. [Getting started](#getting-started)
13. [Repository structure](#repository-structure)
14. [Conventions](#conventions)
15. [Open decisions](#open-decisions)

---

## Status

| Area | State |
| --- | --- |
| **Backend** | Django 5.2 LTS + DRF, nine domain apps, complete API under `/api/v1/`, OpenAPI schema with zero validation errors |
| **Frontend** | Next.js operational: login, dashboard, sales, inventory, payroll, reports, refusals, settings |
| **Auth & security** | Session auth, CSRF, role matrix (27 permissions × 4 roles), rate limiting, prod security hardening |
| **Tests** | 1251 backend, 83 frontend unit, 34 stubbed + 14 live E2E (last verified local run) |
| **Gates** | ruff, ruff-format, mypy, `makemigrations --check`, OpenAPI validation, vitest, Playwright — all exercised locally and in CI |
| **Hardening (Phase D)** | Rate limiting, audit coverage, E2E suite, backups + restore drill, production runbook, observability, local deployment rehearsal — complete |
| **Deployment** | Prod stack (db + api + web) rehearsed locally from `docker-compose.prod.yml`; **target-host (VPS) rehearsal blocked on client decisions** |

The build plan and per-phase gates live in **[`docs/roadmap.md`](docs/roadmap.md)**. Phases A–C
(auth, products, sales, inventory, finance, payroll, reports, settings, dashboard) and Phase D
(hardening) through D5 are complete; D6 is done up to the local rehearsal. **Phase E** (optional
integrations) is deferred until the client decides on a payment provider, fiscal/e-invoicing, and
email — see [Open decisions](#open-decisions).

What a new engineer should read first: this README, then [`docs/roadmap.md`](docs/roadmap.md),
[`docs/ENGINEERING_HANDOFF.md`](docs/ENGINEERING_HANDOFF.md), and the four ADRs in
[`docs/architecture/ADR/`](docs/architecture/ADR/).

---

## Architecture

### Topology

```
        ┌────────────────────────────────────────────────────────────┐
        │                    Host (single VPS)                        │
        │                                                            │
  User──┼──► Nginx (TLS, HTTPS:443) ─┬─► /api/v1/auth/login/  login limit 10r/m
        │                            ├─► /api/v1/            api limit 60r/m, burst 20
        │                            ├─► /health/  ──► api container
        │                            └─► /          ──► web container
        │                                                            │
        │   api (Django + Gunicorn)  127.0.0.1:8000   ◄── never public
        │   web (Next.js)           127.0.0.1:3000   ◄── never public
        │   db  (PostgreSQL 17)      docker network   ◄── never public
        └────────────────────────────────────────────────────────────┘
```

- **Nginx runs on the host** and terminates TLS with Let's Encrypt certificates (spec §8.3, §20.1).
  API and web containers publish only on `127.0.0.1`; PostgreSQL is never reachable off the Docker
  private network.
- Nginx passes the caller's real address in `X-Forwarded-For` and the original scheme in
  `X-Forwarded-Proto`. Django only trusts them when `DJANGO_TRUSTED_PROXY=true` (the compose default),
  so the login throttle keys on the real client (spec §9.3/A5) and `SECURE_SSL_REDIRECT` does not
  redirect-loop behind the proxy.
- Rate limiting is layered: nginx zones at the edge (login 10r/m, api 60r/m) and Django's own
  throttles in the app (login 5/m, writes 60/m). Both have to be satisfied.

### Stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 16 (App Router), TypeScript 5.9, React 19, Tailwind CSS 4 |
| Backend | Django 5.2 LTS + Django REST Framework 3.18, modular monolith |
| Database | PostgreSQL 17 — the single system of record |
| Proxy | Nginx (TLS termination, host) |
| Runtime | Docker Compose on one commercially permitted VPS |
| Async | Redis/Valkey + Celery — optional, added only when a real async workload exists |

### Design principles

- **Single system of record.** PostgreSQL. Dashboards and reports are views over transactions, never
  a second source of truth.
- **Ledger, not mutable state.** Inventory is an append-only movement ledger; current stock is the
  sum of movements. Financial values and payroll figures are frozen once approved.
- **Correct, never overwrite.** Void a record with a required reason instead of deleting; historical
  prices are append-only rows with validity windows.
- **Money is `Decimal`/`NUMERIC(14,2)`**, never floating point. Each transaction line persists the
  price actually used.
- **Backend permissions are authoritative.** The frontend hides what a user cannot do, but the API
  is the enforcement point.
- **Every sensitive operation is audited** with actor, timestamp, entity, action, and reason.
- **Idempotent multi-step operations.** Completing a sale, receiving stock, completing a stock
  count, and approving payroll are atomic and replay-safe.
- Frontend and backend **never import from each other**; they communicate only over the REST
  contract at `/api/v1/` and are built, tested, and deployed independently.

---

## Authentication and authorization

### Sessions, not tokens

Authentication is **session-based** (Django DB sessions + DRF `SessionAuthentication`). The client
logs in once, receives a session cookie, and includes a CSRF token on unsafe requests. There is no
API-key or JWT flow, and no `django.contrib.admin` is installed — the system's own UI is the only
way in.

| Endpoint | Purpose |
| --- | --- |
| `GET  /api/v1/auth/csrf/` | Issue a CSRF token (`{"token": "…"}`) and set the `csrftoken` cookie |
| `POST /api/v1/auth/login/` | Sign in (rate limited 5/minute per address); returns the user profile |
| `POST /api/v1/auth/logout/` | Sign out (204) |
| `GET  /api/v1/auth/me/` | Current session user + role + effective permissions |
| `POST /api/v1/auth/change-password/` | Change the password (rotates the session hash) |

Key behaviour:

- **CSRF:** the token is fetched from `GET /auth/csrf/` and sent back in the `X-CSRFToken` header.
  Cookies are `SameSite=Lax`; the session cookie is `HttpOnly` (`barkot_sessionid`), the CSRF cookie
  is deliberately readable (`csrftoken`).
- **Idle timeout:** sessions expire after a configurable inactivity window (**8 hours default**,
  an Owner setting). An expired session is answered `403 session_expired` (deliberately not 401, so a
  client can distinguish "expired but was logged in" from "never logged in").
- **Forced password change:** an account flagged `is_temporary_password` can reach exactly four
  endpoints — `me`, `csrf`, `change-password`, `logout` — and everything else answers
  `403 password_change_required`. After resetting, the flag clears and the account is unrestricted.
- **Login rate limiting** is 5 attempts per minute per client address (spec §9.3/A5), counted in the
  **database** cache so the budget is shared correctly across Gunicorn workers. Every attempt
  (success or failure) is counted; the 6th in a minute gets `429 throttled` + `Retry-After`.
- Bad credentials return a **uniform** `400 validation_error` — the server never reveals whether the
  username exists. Login failures and successes are written to the audit log.

### Roles and the permission matrix

Users belong to exactly one of four roles (`Role` model, `on_delete=PROTECT`). Each role grants a
fixed set of Django permissions defined in one constant, `ROLE_MATRIX`
(`backend/apps/accounts/permissions.py`), which is seeded into the database and is the **single
source of truth** an Owner reviews.

| Permission | OWNER | MANAGER | CASHIER | BARMAN |
| --- | :-: | :-: | :-: | :-: |
| products.view_products / inventory.view_inventory | x | x | x | x |
| inventory.receive_stock · record_breakage | x | x | – | x |
| inventory.complete_stock_count | x | x | x | – |
| inventory.approve_adjustment | x | x | – | – |
| sales.view_sales · create_sale | x | x | x | – |
| sales.void_sale | x | x | – | – |
| products.manage_categories · manage_products · change_prices | x | – | – | – |
| finance.view_reports · create_expense · approve_expense · manage_expense_categories | x | x | – | – |
| payroll.view_payroll · generate_run · create_deduction · manage_payroll_employees | x | x | – | – |
| payroll.approve_run · mark_paid | x | – | – | – |
| users.manage_employees | x | x | – | – |
| audit.view_audit_log | x | x | – | – |
| accounts.manage_users · manage_roles · manage_settings | x | – | – | – |

Counts: OWNER 27, MANAGER 16, CASHIER 5, BARMAN 5.

**Enforcement engine.** Each capability has one DRF permission class (e.g. `CanApprovePayrollRun`)
that calls `user.has_perm(...)`. The permission backend unions *role grants ∪ direct user grants ∪
group grants*, so the verdict always reflects the matrix rows the Owner reviews — never a second
copy of it. A permission matrix change is applied with `manage.py bootstrap_roles` (plus `--check`
for CI); tests cross-check every class against the matrix (4 roles × all 27 permissions).

**Separation of duties.** The one deliberate split in the matrix: the Manager *generates* the
payroll run, but only the **Owner** *approves* it (`payroll.approve_run`, `payroll.mark_paid`).
Whoever computes the figure must not sign it off.

### The bootstrap path

- **`manage.py create_owner <username>`** creates the first and only Owner. The password is read
  from a no-echo prompt or stdin — **never** an argument or environment variable. `--generate-password`
  prints a random 24-character password once and flags it as temporary; `--check` is a CI preflight.
  The Owner is not a superuser — its authority comes from the matrix.
- Roles are seeded automatically on `migrate` (a `post_migrate` receiver) and verified by
  `manage.py bootstrap_roles --check`.

---

## Security

### Cookie and transport hardening (production)

| Setting | Value |
| --- | --- |
| `DEBUG` | `False`, hard-coded — no `DJANGO_DEBUG` escape hatch |
| `SESSION_COOKIE_HTTPONLY` | `True` (session cookie is invisible to JavaScript) |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `True` by default in prod |
| `SESSION_COOKIE_SAMESITE` / `CSRF_COOKIE_SAMESITE` | `Lax` |
| `SECURE_SSL_REDIRECT` | On when `DJANGO_SECURE_SSL_REDIRECT=true` (compose default) |
| `SECURE_HSTS_SECONDS` | 1 year (31,536,000), include-subdomains, preload |
| `SECURE_CONTENT_TYPE_NOSNIFF` / `X_FRAME_OPTIONS` | `nosniff` / `DENY` |
| JSON renderer/parser | JSON only (no HTML browsable API responses) |

### Anti-fraud and anti-abuse

- **Secret key guard:** prod refuses to boot without a `DJANGO_SECRET_KEY` that is set, distinct from
  the development placeholder, and at least 50 characters — a refused start beats a forged session.
- **No secrets in Git.** `.env` is gitignored; `.env.example` documents every variable.
- **Rate limits:** login 5/m, state-changing requests 60/m per address at the app, echoed at the
  nginx edge. Reads are never throttled.
- **`TRUSTED_PROXY` discipline:** `X-Forwarded-For` is ignored unless the deployment is known to sit
  behind our nginx. Trusting an unauthenticated proxy header would let an attacker pick a fresh
  throttle bucket per attempt.
- **Audit trail:** sales, stock movements, breakages, expenses, payroll, price changes, logins, and
  permission-relevant actions write `AuditLog` rows with actor, action, entity, summary, `before`/
  `after` JSON, and IP. Logs are insert-only.
- **Uniform error codes** (see [API design](#api-design)): a refusal never reveals which permission
  is missing.

### Throttling budget

Every unsafe method, on every endpoint, is throttled to **60 requests/minute per client address**
(`WriteRateThrottle`, installed as DRF's `DEFAULT_THROTTLE_CLASSES`, so a new endpoint cannot be
exempt by omission). Login keeps its stricter `LoginRateThrottle` (5/m), which *replaces* the general
budget on that view. Throttles run after permissions, so 401/403 responses never spend budget.

---

## Domain and database design

PostgreSQL is the system of record. Shared building blocks
(`backend/apps/core/`):

- `MoneyField` = `NUMERIC(14,2)`, `QuantityField` = `NUMERIC(12,3)` — money is never a float.
- `TimeStampedModel` / `ActorStampedModel` — every row records when it changed and who did it.
- `VoidableModel` — records are **voided with a mandatory reason**, not deleted; `objects` hides
  voided rows, `all_rows` includes them.
- `AppendOnlyModel` — `save()` refuses updates and `delete()` always refuses (used by the stock
  ledger and the audit log).
- `IdempotencyRecord` — unique `(scope, key)` claims that make retries safe.

### Sales — `backend/apps/sales/`

- **`Sale`** — `reference S-YYYYMMDD-NNNN` (unique), `status` COMPLETED/VOIDED, `sold_at`,
  denormalised `total`/`amount_paid`, payment status. A sale is voided with a reason and compensating
  stock movements.
- **`SaleItem`** — product, quantity, and **`unit_price` frozen at sale time**, with a
  `price_source` foreign key to the exact `ProductPrice` row used (coins the auditability of "what it
  actually cost that day").
- **`Payment`** — CASH or MOBILE_BANKING, amount, optional external reference. Reports build income
  from `Payment` rows, never from stored totals.
- **Idempotency:** clients send `Idempotency-Key`; the same key replays the *first* response instead
  of creating a duplicate sale. Daily receipt numbers are allocated under a transaction-scoped
  `pg_advisory_xact_lock`, so two concurrent cashiers never get the same `S-…-NNNN` (the unique
  constraint on `reference` is the final authority).

### Inventory — `backend/apps/inventory/`

- **`StockMovement`** — an **append-only ledger**; current stock is defined as the sum of
  movements, and there is deliberately no `stock` column on products. Kinds: RECEIPT, SALE,
  SALE_VOID, BREAKAGE, COUNT_VARIANCE, STOCK_IN, STOCK_OUT. Every movement has exactly one source
  FK (enforced by a check constraint), a direction derived from its kind (never hand-set), and an
  optional unit cost for valuation.
- **`StockReceipt` + items** — DRAFT→COMPLETED; receiving posts RECEIPT movements.
- **`StockCount` + items** — DRAFT→COMPLETED→APPROVED. The count *snapshots* the ledger balance at
  line creation; **only approval writes COUNT_VARIANCE movements**, and only a Manager/Owner can
  approve. A Cashier can count but not approve.

### Finance — `backend/apps/finance/`

- **`Expense`** — category, amount, business-local `incurred_on`, status RECORDED→APPROVED→VOIDED,
  with `approved_at`/`approved_by`. Only approved, non-voided expenses count in reports.
- **Balance is derived, not stored:** income = sum of `sales.Payment`, minus approved expenses,
  minus approved payroll. `net` = income − expenses − payroll.

### Payroll — `backend/apps/payroll/`

- **`Employee`** — payroll-side companion (1:1 to the `EmployeeProfile` person record) with
  `monthly_wage`. One employee per payroll run is enforced.
- **`PayrollRun`** — GENERATED→APPROVED→PAID (or CANCELLED), one run per month. Manager generates,
  Owner approves and marks paid. Totals (`gross_total`, `deduction_total`, `net_total`) are computed.
- **`PayrollItem`** — per-employee stored `gross_amount`, `total_deductions`, `net_amount` frozen at
  approval. Deductions (ADVANCE, ABSENCE, LATE, OTHER) may not exceed gross.
- **`PayrollDeduction`** — type, amount, reason, date. Statutory deduction types are deliberately
  absent until the client specifies the calculation rules.

### Users and audit — `backend/apps/users/`, `backend/apps/audit/`

- **`EmployeeProfile`** — the *person* (full name, position, start date), archivied, never deleted,
  optionally linked to a login account.
- **`AuditLog`** — insert-only: actor, action (CREATE/UPDATE/DELETE/VOID/LOGIN/LOGOUT/
  FAILED_LOGIN/APPROVE), object type + id, summary, `before`/`after` JSON, IP, UTC timestamp. Indexed
  by object, time, and actor+time.

The full ADR-level rationale for the important choices is in
[`docs/architecture/ADR/`](docs/architecture/ADR/).

---

## API design

- **Versioned** at `/api/v1/` (DRF namespace versioning). OpenAPI schema and Swagger docs live at
  `/api/schema/` and `/api/docs/`, beside the version so a v1 client need not know about v2.
- **One error envelope for every failure:**

  ```json
  {"error": {"code": "validation_error", "message": "…", "details": {"field": ["…"]}}}
  ```

  Codes distinguish *client* mistakes (`validation_error`, `not_found`), *session* states
  (`not_authenticated`, `session_expired`, `password_change_required`), *authorisation*
  (`permission_denied`), *business rules* (`insufficient_stock`, `invalid_state_transition`,
  `immutable_record`, `idempotency_key_reuse` — all 409), and *abuse* (`throttled` 429).
- **Pagination** with a hard cap: default page size 20, maximum 200 (`/?page_size=`), response
  `{count, page_size, page, pages, results}`.
- Every endpoint satisfying the contract (auth, error envelope, JSON, pagination, version) is checked
  automatically by the **contract suite** (see below).
- Health endpoints `/health/live` (process up) and `/health/ready` (DB reachable) are operational
  probes, deliberately free of business logic.

---

## Testing and CI

Testing is layered: fast isolated checks first, deep integration in the middle, and a real browser
against a real stack at the top.

| Layer | Tool | What it proves |
| --- | --- | --- |
| Backend unit/integration | pytest (**1251 tests**) | Domain invariants, permission matrix cross-product, session rules, auth flows, throttles, idempotency under real thread contention, prod config guards, all five §23.1 business scenarios |
| API contract suite | `backend/tests/api/contract.py` | Every mounted endpoint satisfies invariant rules (auth, envelope, JSON, pagination, version) — auto-discovery, exemptions require a reason. A new endpoint is checked automatically |
| Access sweep | `backend/tests/api/test_access_sweep.py` | Real signed-out requests to every route assert 401/403 with the right envelope; the sweep is pinned non-vacuous and mutation-checked |
| Endpoint audit | `backend/tests/api/test_audit_coverage.py` | Every state-changing endpoint asserts exactly one audit row for each of its 31 scenarios |
| Frontend unit | vitest (**83 tests**) | Component and logic behaviour |
| E2E stubbed | Playwright (**34 specs**) | Screens behave against stubbed states a real server will not produce on demand (dead backend, 502, forced password change) |
| E2E live | Playwright (**14 specs**) | Browser against a real Django + Postgres: real session, real CSRF, real 403, real rows. A stub cannot catch frontend/backend drift; this half does |

**CI** (`.github/workflows/ci.yml`, GitHub Actions) runs the same gates on `main` and PRs:
backend — `ruff check`, `ruff format --check`, `mypy .`, `pytest`, `makemigrations --check`,
OpenAPI validation; frontend — lint, Prettier, `tsc --noEmit`, vitest, production build; E2E — the
stubbed suite then the live suite as two separate invocations (roles seed via `post_migrate`;
Playwright live runs its own Django on port 8010 against a disposable `*_e2e` database).

Run everything locally with the root `Makefile`: `make ci` mirrors the pipeline step-for-step
(POSIX shell), or run each app's commands directly (see [Getting started](#getting-started)).

---

## Deployment and operations

### Design

- One VPS (client-chosen provider), Docker Compose swarm-free: `db`, `api` (Gunicorn), `web`
  (Next.js standalone). Host nginx terminates TLS and proxies.
- `docker-compose.prod.yml` is the production definition; `.env.example` documents every required
  variable. Prod refuses to boot without a real secret key and sets DEBUG off unconditionally.
- No `collectstatic` step: the API serves no static assets (the frontend is a separate container).
  Roles seed on `migrate`; only the Owner account is created explicitly.

### The deployment sequence

```bash
git clone https://github.com/NahumDm/barkot_internal_system.git
cd barkot_internal_system
cp .env.example .env            # fill in real secrets (secret key ≥ 50 chars, DB password)
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
docker compose --env-file .env -f docker-compose.prod.yml exec api python manage.py migrate --no-input
docker compose --env-file .env -f docker-compose.prod.yml exec -it api python manage.py create_owner owner
sudo cp infrastructure/nginx/nginx.conf /etc/nginx/nginx.conf
sudo cp infrastructure/nginx/conf.d/barkot.conf /etc/nginx/conf.d/barkot.conf
sudo nginx -t && sudo systemctl reload nginx
```

### Runbooks

| Document | Covers |
| --- | --- |
| [`docs/runbooks/production.md`](docs/runbooks/production.md) | Initial deployment, service operations, backup/restore, **rollback procedure**, troubleshooting, verification checklist (D4 gate: "a second person can deploy and roll back from this document alone") |
| [`docs/runbooks/backup-restore.md`](docs/runbooks/backup-restore.md) | Daily `pg_dump` backups, restore, and the **automated restore drill** into a scratch database |
| [`docs/runbooks/deployment-rehearsal.md`](docs/runbooks/deployment-rehearsal.md) | Full-stack rehearsal checklist, with the executed local rehearsal logged (2026-10-08) |

**Backups** (`infrastructure/scripts/`): `backup.sh` (pg_dump), `restore.sh`, and a
`restore-drill.sh` that backs up, restores into a scratch DB (`barkot_restore_drill_<timestamp>`),
and reconciles row counts — because an untested backup is a hypothesis. A Windows-drive equivalent
(`restore-drill.ps1`) documents the procedure.

**Rehearsal status.** The D6 gate ("full stack starts from `docker compose.prod.yml` with real
secrets") passed in a **local rehearsal** (2026-10-08): images built, stack Up, migrations applied,
`/health/live` + `/health/ready` 200, owner login 200, `X-Request-ID` present, `nginx -t` clean.
The remaining **milestone rehearsal on a real Ubuntu 24.04 VPS with a domain and Let's Encrypt
certs** is blocked on the client's VPS/domain decision (open questions 9/10).

---

## Observability

- **Request context:** every request carries a `request_id` (from nginx's `$request_id` or generated),
  written back in the `X-Request-ID` header and attached to log records along with the acting
  `user_id`.
- **Structured logs** (dev and prod) include `request_id` and `user_id` for correlating a user action
  with the requests that produced it.
- **Health probes:** `/health/live` and `/health/ready` are consumed by Docker healthchecks and
  nginx; `/health/ready` turns 503 when the database is unreachable.
- **Alerting guidance** (documented in the production runbook): alert on 5xx rate, on `/health/ready`
  returning 503, and on `/health/live` failing.

---

## Engineering notes and major decisions

The full write-ups are in [`docs/roadmap.md`](docs/roadmap.md); the highlights show why the design
looks the way it does.

1. **Session auth avoids a recursion trap.** Reading `request.user` from inside the authenticator
   recursed to a stack overflow when a session expired. Sessions are now ended by flushing the
   session directly, never by calling `logout()`; session rules take the already-resolved user as an
   argument.
2. **The password policy was not rejecting anything.** Django 5.2 raises
   `ValidationError`, not a non-existent `PasswordValidationError`; the `except` clause threw an
   `AttributeError` while handling a rejection, turning every refusal into a 500. Caught as
   `ValidationError` now.
3. **The forced-password rule had made its own endpoint unreachable.** The CSRF view sat outside the
   `password_change_required` allow-list, so a user on a temporary password could not fetch a token
   to change it. The allow-list is exactly four views and is pinned by a test.
4. **The permission gate used to be a test stand-in.** An old test URLconf defined its own
   permission classes, so "Cashier cannot approve payroll" was true of a test, not the app. Shipped
   permission classes (one per capability, resolving through `has_perm` against the matrix rows) now
   replace the stand-in, and a 4×27 cross-product test pins the matrix.
5. **401s were assumed, not verified.** An access sweep of real signed-out requests over every route
   surfaced that the API docs view answers 401 outside the JSON envelope. Those responses are now
   asserted on exactly what they do (correct status + `WWW-Authenticate`), with the reason recorded.
6. **Duplicate-sale retries are impossible by design.** Same `Idempotency-Key` replays the first
   result; a fingerprint hashes canonicalised `Decimal` amounts (never their string form) and the
   caller's `sold_at`; the next-daily-reference counter runs under a `pg_advisory_xact_lock`.
   Concurrency tests are `transaction=True` and verified by mutation.
7. **TLS-in-front is trusted only when the proxy is trusted.** `SECURE_PROXY_SSL_HEADER` is wired
   only behind `DJANGO_TRUSTED_PROXY=true`; without it, `SECURE_SSL_REDIRECT` behind nginx would
   redirect-loop (2026-10-08, guarded by `tests/settings/test_prod_guards.py`).
8. **No `django.contrib.admin`, no API keys, no JWT.** The only client is the same-origin web app;
   reducing the surface is a feature.

---

## Documentation

| Path | Contents |
| --- | --- |
| `docs/roadmap.md` | Phase-by-phase plan (spec A28), gates, status, open questions |
| `docs/architecture/ADR/` | Architecture decision records 0001–0004 (layout, Python runtime, phase-0b scope, vertical slice) |
| `docs/ENGINEERING_HANDOFF.md` | Operator-facing state of the world, known gaps, verified gate baselines |
| `docs/ADDING_AN_ENDPOINT.md` | How to add an endpoint without breaking the contract/audit/completeness gates |
| `docs/runbooks/` | Production, backup-restore, deployment-rehearsal |
| `docs/business/client-decisions.md` | Open decisions that steer scope |
| `docs/ui-ux/`, `docs/architecture/*.docx` | The client-authored UI/UX and architecture specifications |

---

## Getting started

All-in dev stack (database + API + web with hot reload):

```bash
docker compose up -d
docker compose exec api python manage.py create_owner owner
# open http://localhost:3000 (redirects to /dashboard)
```

Per-app (without Docker for the app code):

1. **Database** (the only service needed): `docker compose up -d db`
2. **Backend:** `cd backend; python -m venv .venv; .\.venv\Scripts\pip install -r requirements/dev.txt`
   on Windows (POSIX: `make install-backend`). Then `.\.venv\Scripts\python manage.py runserver 8000`.
   See [`backend/README.md`](backend/README.md).
3. **Frontend:** `cd frontend; npm ci; npm run dev` → http://localhost:3000
4. **All-in:** `docker compose up -d` (db + api + web with hot reload)

Tests:

```bash
make ci              # local parity with the CI pipeline (POSIX shell)
# or individually:
cd backend    && .\.venv\Scripts\python.exe -m pytest   # backend suite
cd frontend   && npm run lint && npm run test -- --run  # lint + vitest
npm run test:e2e:stubbed                                # stubbed E2E (Node only)
E2E_DB_PASSWORD='<your DJANGO_DB_PASSWORD>' npm run test:e2e:live   # live E2E
```

The live E2E suite starts its own Django on port 8010 against a disposable `barket_e2e` database
and reseeds it on every run. `seed_e2e --reset` refuses to flush any database whose name does not
end in `_e2e`.

---

## Repository structure

```
barkot_internal_system/
├── frontend/             Next.js + TypeScript application (Next.js 16, App Router)
├── backend/              Django 5.2 + DRF application (modular monolith, 9 domain apps)
├── infrastructure/       Docker (multi-target backend/frontend), Nginx config, ops scripts
├── docs/                 Roadmap, ADRs, runbooks, handoff, client decisions, specs
├── .github/workflows/    CI pipelines (backend · frontend · e2e)
├── docker-compose.yml    Dev stack (db + api + web, hot reload)
├── docker-compose.prod.yml  Production stack definition
├── Makefile              CI-parity orchestration (lint/typecheck/test/…)
└── .env.example          Environment template (never commit .env)
```

---

## Conventions

- **Branching:** `main` (production-ready), `staging` (release candidate), `feature/*`.
- **Commits:** conventional-style prefixes (e.g. `feat(backend):`, `docs(runbook):`,
  `style(backend):`); one logical change per commit; commit only when the worktree contains the
  intended phase change.
- **Adding API surface** requires passing the contract suite and adding an audit scenario — both are
  enforced automatically; see `docs/ADDING_AN_ENDPOINT.md`.
- **No secrets** in Git, in committed `settings` overrides, or in test fixtures that ship.

---

## Open decisions

None block the running system, but several set the remaining scope
(`docs/business/client-decisions.md`):

| # | Decision | Affects |
| --- | --- | --- |
| 4 | Stock-count frequency and a formal closing time (implies report cut-offs) | C4 reporting boundaries |
| 5 | Payroll additions, overtime, absences | Payroll |
| 6 | Deduction approval policy and statutory calculations | Payroll |
| 8 | Fiscal / e-invoicing technical requirements | Phase E |
| 9, 10 | Commercially permitted VPS provider and ETB payment method | **Deployment rehearsal (D6) and Phase E** |