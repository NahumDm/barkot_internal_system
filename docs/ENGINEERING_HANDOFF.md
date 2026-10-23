# Barkot Engineering Handoff

**Generated:** 2026-10-05, maintained through D2 on 2026-10-08  
**Repository:** `C:\dev\barkot_internal_system`  
**Branch:** `main`  
**HEAD:** `de05ebe feat(backend): D1 - Audit coverage: a test per state-changing endpoint` (D2 commit follows)  
**Remote:** `main` tracks `origin/main`; push after every verified commit.

This document is a continuation map for an engineering model. It is not a substitute for reading the source. The code and normative specifications win over this document if they disagree.

## Start Here

1. Read `docs/business/client-decisions.md`.
2. Read the architecture specification at `docs/architecture/Barkot_Software_Architecture_Specification.docx`.
3. Read the ADRs in `docs/architecture/ADR/`.
4. Read the UI/UX specification at `docs/ui-ux/Barkot_UI_UX_Design_Specification.docx` before changing screens.
5. Verify the current implementation against this handoff before relying on the status below.
6. Read `docs/ADDING_AN_ENDPOINT.md` before adding another API resource.

The architecture document can be extracted on Windows with:

```powershell
python -c "import zipfile,xml.etree.ElementTree as ET;W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}';r=ET.fromstring(zipfile.ZipFile(r'docs/architecture/Barkot_Software_Architecture_Specification.docx').read('word/document.xml'));[print(''.join(t.text or '' for t in p.iter(W+'t'))) for p in r.iter(W+'p')]"
```

## Current Phase Status

### Complete

- A0-A10 foundation: session authentication, CSRF, throttling, permissions, idempotency, production guards, seed safety, and contract enforcement.
- B0-B4: typed frontend client, protected route group, login/password flows, product catalogue, price history, product maintenance.
- B5: sale creation and voiding are implemented and proven at HTTP/service level. The roadmap claim remains deliberately open because income was originally not browser-readable; C1 now exposes a read-only finance balance endpoint, but the B5 status should still be reviewed explicitly rather than silently changed.
- B6: endpoint guide at `docs/ADDING_AN_ENDPOINT.md`.
- C1: finance balance, expense categories, expense recording, approval, audit records, API client, and finance screens.
- C2: payroll employees, monthly runs through generated→approved→paid, deductions with a reason, API client, and payroll screens.
- C3: inventory receipts, breakage/waste, stock counts, variance approval, movement history, ledger-backed stock overview, API client, and inventory screens.
- C4: date-filtered financial/inventory/payroll reports with PDF downloads in the UI and CSV compatibility on the API; stubbed and live E2E.
- C5: staff account administration, the read-only roles catalogue, and the system settings row. Owner-only — a Manager is refused at every endpoint and on the screen. Acceptance tests, API client, settings screen, and stubbed + live E2E.
- C6: role-scoped dashboard summary. One read-only `GET /dashboard/` whose tiles delegate to the services that own them (balance, stock balance, sales totals, latest run), each `null` when the role lacks the grant. Acceptance tests, API client, dashboard screen, and stubbed + live E2E. **Phase C is complete.**
- D0: rate limiting on all state-changing endpoints (spec §9.3). Every POST/PUT/PATCH/DELETE on every endpoint, 60 a minute per client address, installed as DRF's `DEFAULT_THROTTLE_CLASSES` so a new endpoint cannot be exempt by omission; reads are never throttled and login keeps its stricter 5/m. Configuration assertions, reads-don't-spend, per-address isolation, login/write budget separation, window reset, and the load test that expects 429.
- D1: audit coverage (P06). `backend/tests/api/test_audit_coverage.py` holds one scenario per state-changing endpoint (31 method/path pairs) that drives the real view and asserts exactly one new `AuditLog` row with the right action, object type, actor, object id and summary, plus a completeness test that compares the discovered unsafe surface against the scenario table — a new endpoint with no scenario fails the suite, and a mutation re-exposed on `SalesViewSet` fails it too (DRF drops `http_method_names`-blocked methods from discovery, so the two surfaces cannot drift apart). Writing it closed real gaps: product/category `perform_create` and `set_price` logged `actor=None`; `open_stock_count`, payroll's `add_deduction`, a new `add_employee` service, and product/category update/delete services did not record at all; `AuditLog.Action.DELETE` did not exist.
- D2: the five §23.1 scenarios mapped onto the live suite, green locally and in CI. Scenario 1.1's income half: `b5-sale.spec.ts` now asserts the dashboard Takings and Transactions tiles after the sale, not just the stock movement. Scenario 1.4's deduction: `payroll.spec.ts` records a 500 "Salary advance" with a written reason and ties the deductions register to the run (total_deductions 500.00 / net_amount 11500.00) and to `reports.spec.ts`, which reads the run as its net (financial payroll_total, payroll tab tiles, deductions-by-type panel and the PDF). Scenarios 2 and 3 (C3's first browser coverage): new `stock.spec.ts` — the Barman receives 50 units at 20.00/unit (receipt completed on the wire with line cost 1000.00, one IN movement, shelf 40 → 90) and a Manager opens a count at 90, counts 89, completes it (variance −1.000), a Cashier is refused approve over the wire (backend's own 403 envelope), and the Manager's approval posts a COUNT_VARIANCE OUT 1.000 movement that lands in the variance report. Scenario 1.5's refusals: new `refusals.spec.ts` — the Cashier's payroll no-access note, a 403 on approve-run and on set-price, and the Owner (the only role with `products.change_prices`) getting a 201 where the Cashier got 403. The wire-based refusals needed `frontend/tests/live/wire.ts` (same-origin `page.evaluate(fetch)`, CSRF token from the cookie, so the 403 is Django's permission answer rather than a CSRF defence). The seed (`seed_e2e.py`, `environment.ts`) now also creates a Barman.

### Next

**D3 — Automated backups (restore drill)** is next in the roadmap order (`docs/roadmap.md` carries the D1-D6 table); the gate is "restore into a scratch database and reconcile". D2's E2E gate is now green both locally and via the CI workflow (`.github/workflows/ci.yml` — it pre-existed and already ran the backend gates, lint, prettier, typecheck, vitest, the build and both Playwright projects; D2 only had to keep it green), and the live suite covers every §23.1 scenario. D2 is done — see the rule in Non-Negotiable Rules and the budgets in Verified Gates.

## API Surface

Mounted in `backend/config/api_urls.py` under `/api/v1/`:

- `/auth/`
- `/products/`
- `/sales/`
- `/finance/`
- `/inventory/`
- `/payroll/`
- `/reports/`
- `/users/`
- `/roles/`
- `/settings/`
- `/dashboard/`

Schema and Swagger are mounted beside the version at `/api/schema/` and `/api/docs/`.

### Finance C1

- `GET /api/v1/finance/balance/?start=YYYY-MM-DD&end=YYYY-MM-DD`
- `GET/POST /api/v1/finance/categories/`
- `GET /api/v1/finance/expenses/`
- `GET /api/v1/finance/expenses/{id}/`
- `POST /api/v1/finance/expenses/`
- `POST /api/v1/finance/expenses/{id}/approve/`

Balance periods require explicit business-local dates. The service converts date ranges through `apps.core.business_time`; do not use a browser timezone as an accounting period.

Expense voiding is not an HTTP action because the existing permission catalogue has no `finance.void_expense` permission. Do not invent one without a product/architecture decision.

### Inventory C3

- `GET/POST /api/v1/inventory/receipts/`
- `GET /api/v1/inventory/receipts/{id}/`
- `GET/POST /api/v1/inventory/breakages/`
- `GET /api/v1/inventory/breakages/{id}/`
- `GET/POST /api/v1/inventory/counts/`
- `GET /api/v1/inventory/counts/{id}/`
- `POST /api/v1/inventory/counts/{id}/complete/`
- `POST /api/v1/inventory/counts/{id}/approve/`
- `GET /api/v1/inventory/movements/`
- `GET /api/v1/inventory/movements/{id}/`

Inventory writes call the existing services in `apps.inventory.services`. The movement ledger is authoritative; never add or update a cached stock field. Product list responses now include `current_stock`, derived from the ledger.

### Payroll C2

- `GET /api/v1/payroll/employees/`
- `GET/POST /api/v1/payroll/runs/` — POST generates the month
- `GET /api/v1/payroll/runs/{id}/`
- `GET /api/v1/payroll/runs/{id}/items/`
- `POST /api/v1/payroll/runs/{id}/approve/`
- `POST /api/v1/payroll/runs/{id}/mark-paid/`

Payroll runs flow generated→approved→paid. Deductions retain a reason. Statutory tax, overtime, absence, and deduction calculations are deliberately not invented (client decisions still open).

### Reports C4

- `GET /api/v1/reports/financial/?start=&end=`
- `GET /api/v1/reports/inventory/stock-balance/?date=`
- `GET /api/v1/reports/inventory/variance/?start=&end=`
- `GET /api/v1/reports/payroll/?start=&end=`
- `GET /api/v1/reports/...?export=pdf` (CSV also accepted)

All report endpoints take the same `?start=&end=` business-date range. JSON is the default; `?export=pdf` returns the report as a PDF attachment and `?export=csv` is retained for compatibility. The reports screen offers PDF downloads. Reports aggregate authoritative domain data; they never keep parallel totals.

### Accounts C5

- `GET /api/v1/users/?page_size=200`
- `POST /api/v1/users/`
- `GET/PATCH /api/v1/users/{id}/`
- `GET /api/v1/roles/?page_size=200`
- `GET /api/v1/settings/`
- `PATCH /api/v1/settings/`

The user create/edit paths accept a temporary password and a role code. Role codes are UPPERCASE (`OWNER`, `MANAGER`, `CASHIER`, `BARMAN`). `PATCH /settings/` is a partial update and records `updated_by`. Every endpoint here is Owner-only enforced through `accounts.manage_users` / `accounts.manage_roles` / `accounts.manage_settings` permission classes; a Manager receives a plain 403 with no side effects.

### Dashboard C6

- `GET /api/v1/dashboard/?start=YYYY-MM-DD&end=YYYY-MM-DD`

One read-only aggregate for the whole screen. Both bounds are optional but must be supplied together; absent both, the period defaults to the current business month-to-date in Africa/Addis_Ababa. Each section delegates to the service that owns it — `finance_balance`, `inventory_stock_balance`, `sales_totals`, and `PayrollRunSerializer` for the latest run — and the endpoint computes nothing of its own, so the screen cannot disagree with the source it links to.

Sections are gated on `finance.view_reports`, `payroll.view_payroll`, `sales.view_sales` and `inventory.view_inventory` through `user.has_perm()`; a refused section is `null` on the wire rather than omitted. `payroll` is `null` both when the role lacks the grant **and** while no run exists, so the frontend consults the session's permission list (presentation only) to word "not your role" apart from "no run yet".

## Non-Negotiable Rules

- `ROLE_MATRIX` in `backend/apps/accounts/permissions.py` is the only role-to-permission mapping. Views use `user.has_perm()` through permission classes; never branch on `user.role`.
- Every endpoint is private by default, session-authenticated, JSON-only, versioned, and uses `BarkotPagination` for list responses. The automatic contract suite discovers mounted endpoints.
- Every state-changing request (POST/PUT/PATCH/DELETE) is throttled at 60 a minute per client address through DRF's `DEFAULT_THROTTLE_CLASSES`; reads are never throttled. `LoginView` is the only override (5/m, stricter, replaces rather than stacks). Do not set `throttle_classes` on a view without the reason written down. See `backend/apps/core/throttling.py`.
- Expected domain failures raise `BARKOTDomainError` subclasses. The API envelope is `{"error": {"code", "message", "details"?}}`.
- Money is Decimal/NUMERIC and explicitly ETB. Never use floats.
- State-changing services validate first, run atomically, write all linked domain/ledger records, audit the event, then return. The view layer must pass the acting user as `actor`: an audit row with `actor=None` is a defect, not a fallback.
- A new state-changing endpoint is not finished until `backend/tests/api/test_audit_coverage.py` has a scenario for it. The completeness test discovers mounted unsafe methods and fails on any method/path the scenario table does not know, so the coverage cannot be skipped by omission.
- Financial and stock records are voided or reversed, never deleted. Stock movements are append-only.
- Idempotency belongs at the service layer for retryable financial/stock writes.
- Reports use Africa/Addis_Ababa business dates while the database stores UTC.
- Sales are individual completed transactions. Payment methods are exactly CASH and MOBILE_BANKING.
- Inventory covers sellable products/beverages, not ingredients, recipes, BOMs, or kitchen production.
- Payroll statutory rules remain unconfirmed and must not be guessed.
- Protected frontend pages belong under `src/app/(app)/`; that route group is the structural auth boundary.

## Implementation Map

### Backend

- Shared domain rules: `backend/apps/core/`
- Permissions: `backend/apps/accounts/permissions.py`
- Finance: `backend/apps/finance/models.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`
- Inventory: `backend/apps/inventory/models.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`
- Payroll: `backend/apps/payroll/models.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`
- Reports: `backend/apps/reports/views.py`, `services.py`
- Accounts (roles/settings/users): `backend/apps/accounts/services.py`, `schemas.py`, `admin_views.py`, `urls.py`
- Dashboard: `backend/apps/dashboard/services.py`, `serializers.py`, `views.py`, `urls.py`
- API mounting: `backend/config/api_urls.py`
- Contract tests: `backend/tests/api/test_contract.py`
- D1 audit coverage tests: `backend/tests/api/test_audit_coverage.py`
- C1 acceptance tests: `backend/apps/finance/tests/test_finance_api.py`
- C3 acceptance tests: `backend/apps/inventory/tests/test_inventory_api.py`
- C4 acceptance tests: `backend/apps/reports/tests/`
- C5 acceptance tests: `backend/apps/accounts/tests/test_admin_api.py`
- C6 acceptance tests: `backend/apps/dashboard/tests/`

### Frontend

- Shared typed client: `frontend/src/lib/api/client.ts`
- Finance client/screens: `frontend/src/lib/api/finance.ts`, `frontend/src/features/finance/`
- Inventory client/screens: `frontend/src/lib/api/inventory.ts`, `frontend/src/features/inventory/`
- Payroll client/screens: `frontend/src/lib/api/payroll.ts`, `frontend/src/features/payroll/`, `frontend/src/app/(app)/payroll/`
- Reports client/screens: `frontend/src/lib/api/reports.ts`, `frontend/src/features/reports/`, `frontend/src/app/(app)/reports/`
- Settings client/screen: `frontend/src/lib/api/admin.ts`, `frontend/src/features/settings/settings-page.tsx`, `frontend/src/app/(app)/settings/`
- Dashboard client/screen: `frontend/src/lib/api/dashboard.ts`, `frontend/src/features/dashboard/dashboard-page.tsx`, `frontend/src/app/(app)/dashboard/`
- Product list contract: `frontend/src/lib/api/products.ts` and `backend/apps/products/serializers.py`
- Protected finance routes: `frontend/src/app/(app)/finance/`
- Protected inventory routes: `frontend/src/app/(app)/inventory/`
- Stubbed E2E: `frontend/tests/e2e/`
- Live E2E: `frontend/tests/live/` — shared throttle-aware `signIn` in `frontend/tests/live/signin.ts`; the suite runs alphabetically (`b5-sale > dashboard > payroll > refusals > reports > settings > stock`), one worker

The C3 frontend form currently handles one product line at a time. Multi-line receipt/breakage/count UX is a reasonable follow-up, but it must preserve the existing service contract that validates duplicate products and all-or-nothing writes.

## Verified Gates

### Backend

Run from `backend`:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe .
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py spectacular --validate --file NUL
.\.venv\Scripts\python.exe -m pytest -q
```

Last verified result: **1471 passed**, with 55 known deprecation warnings from `drf_spectacular` on the current Python runtime. mypy is clean across **202 files**. OpenAPI validation had 0 errors and 7 enum-name warnings (three `status` collisions, two `quantity_mode` collisions, `PaymentStatusEnum`, and `CodeEnum` — the last from the roles endpoint; all cosmetic).

For the local Compose database, use the project defaults explicitly when running host tooling:

```powershell
$env:DJANGO_DB_NAME='barkot'
$env:DJANGO_DB_USER='barkot'
$env:DJANGO_DB_PASSWORD='barkot'
$env:DJANGO_DB_HOST='127.0.0.1'
$env:DJANGO_DB_PORT='5433'
```

The development PostgreSQL container is `barkot-dev-db-1`, exposed at `127.0.0.1:5433`. Its local application password was reset to `barkot` during validation; this is machine state, not a committed credential.

### Frontend

Run from `frontend`:

```powershell
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
npm run test:e2e
```

Last verified: **125 Vitest tests**, **48 stubbed Playwright tests** and **19 live Playwright tests** green after the full audit. The live run required these local-only overrides because the checked-in harness defaults still use historical `barket` names while this Compose volume uses `barkot`:

```powershell
$env:E2E_DB_NAME='barkot_e2e'
$env:E2E_DB_USER='barkot'
$env:E2E_DB_PASSWORD='barkot'
npm run test:e2e:live
```

**The live suite now makes fifteen sign-ins in one run, and A5 allows five a minute per address.** Every live spec must sign in through `frontend/tests/live/signin.ts`, which waits the window out and retries; a spec with its own non-retrying copy fails on the first 429 (payroll's did when C6 added two more logins, and `b5-sale`'s did at D1). Do not add a sign-in path that is not the shared helper, and keep `test.setTimeout(240_000)` on any test that signs in.

**The live files also depend on each other's leftovers** — `reports` reads the run `payroll` approved (with its deduction) and the sale `b5-sale` voided, and `stock` counts on the shelf the receipt it receives — so `playwright.config.ts` sets `workers: 1` whenever the live project is selected. `fullyParallel: false` alone only serializes tests *within* a file; separate files still spread across workers, which raced `reports` ahead of `payroll`'s approval. The alphabetical file order (`b5-sale > dashboard > payroll > refusals > reports > settings > stock`) is the contract; `stock` is last because receive and count approval change the stock the earlier stories leave alone, and `reports` must still see a pristine variance report.

**D0 added a second budget: 60 state-changing requests a minute per client address (reads are free).** The live suite runs far below it today; if a future spec loops mutations, count them the way sign-ins are counted before raising a spec's intensity.

Do not casually rename the harness or seed safety strings; they are covered by tests and may reflect CI naming. Treat the local override and the committed CI configuration as separate concerns.

## Known Gaps and Decisions

- B5's original browser income claim was blocked before C1 because no finance read existed. C1 now exposes the read. Decide explicitly whether to amend the roadmap status or add a B5 browser assertion; do not mark it silently.
- C3 inventory's normative scenarios 2 and 3 now have browser coverage in `stock.spec.ts` (Barman receive, Manager count + approval, Cashier refusal over the wire); the receive and count screens have no Process-and-Banner, so that spec's assertions read the wire and the movement ledger instead.
- The frontend has some existing non-blocking lint warnings in older product/sales files when running full lint without `--quiet`; do not mix them up with new errors.
- Open client decisions remain: physical count frequency/closing time, payroll additions/overtime/absence, deduction/statutory calculations, fiscal/e-invoicing, domain availability, VPS, and payment method.
- The repository and product are named `barkot`; some older internal strings and live E2E defaults say `barket`. Verify before changing any such string because some are intentional test guards and some are stale naming.
- `zone=login` (10r/m) is now wired onto `location /api/v1/auth/login/` in `conf.d/barkot.conf` (validated with `nginx -t` during the 2026-10-08 D6 local rehearsal), beside Django's 5/m app limit.

## Safe Next Action

Phases A–C and D0–D6 (docs/impl) are complete. Read the D1-D6 table in `docs/roadmap.md`.

1. A local D6 rehearsal ran 2026-10-08 (stack up from `docker-compose.prod.yml`, migrate, health 200/200, owner login 200, `X-Request-ID` present, nginx `nginx -t` clean). The remaining D6 gate — the milestone rehearsal on a real Ubuntu 24.04 VPS with a domain and Let's Encrypt certs — is blocked on open clients decisions 9/10 (`docs/business/client-decisions.md`).
2. Phase E (optional integrations) is externally blocked on the same decisions: Chapa/payment, fiscal/e-invoicing, email, async jobs.
3. Keep the contract suite green when touching the API surface — it discovers mounted endpoints automatically. A new state-changing endpoint also needs a scenario in `backend/tests/api/test_audit_coverage.py` (the completeness test enforces this).
4. Run the full gate set in `## Verified Gates` before every commit; counts there are the last verified baseline.
5. Commit only when the worktree contains the intended phase changes, and push after the commit.
