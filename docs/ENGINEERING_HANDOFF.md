# Barkot Engineering Handoff

**Generated:** 2026-10-05  
**Repository:** `C:\dev\barkot_internal_system`  
**Branch:** `main`  
**HEAD:** `cfad8f7 feat: add inventory workflows and ledger views`  
**Remote:** `main` is clean and matches `origin/main`.

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
- C4: date-filtered financial/inventory/payroll reports with CSV export; stubbed and live E2E.
- C5: staff account administration, the read-only roles catalogue, and the system settings row. Owner-only — a Manager is refused at every endpoint and on the screen. Acceptance tests, API client, settings screen, and stubbed + live E2E.

### Next

**C6 Dashboard summary** is next in the roadmap order. Displayed figures must reconcile to the underlying authoritative sources (finance balance, payroll run states, stock ledger) rather than introduce parallel totals. The dashboard route shell is the placeholder left behind at `src/app/(app)/dashboard/`.

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
- `GET/POST /api/v1/payroll/runs/`
- `GET /api/v1/payroll/runs/{id}/`
- `POST /api/v1/payroll/runs/{id}/generate/`
- `POST /api/v1/payroll/runs/{id}/approve/`
- `POST /api/v1/payroll/runs/{id}/pay/`

Payroll runs flow generated→approved→paid. Deductions retain a reason. Statutory tax, overtime, absence, and deduction calculations are deliberately not invented (client decisions still open).

### Reports C4

- `GET /api/v1/reports/financial/?start=&end=`
- `GET /api/v1/reports/inventory/stock-balance/?date=`
- `GET /api/v1/reports/inventory/variance/?start=&end=`
- `GET /api/v1/reports/payroll/?start=&end=`
- `GET /api/v1/reports/...?export=csv`

All report endpoints take the same `?start=&end=` business-date range and CSV format. Reports aggregate authoritative domain data; they never keep parallel totals.

### Accounts C5

- `GET /api/v1/users/?page_size=200`
- `POST /api/v1/users/`
- `GET/PATCH /api/v1/users/{id}/`
- `GET /api/v1/roles/?page_size=200`
- `GET /api/v1/settings/`
- `PATCH /api/v1/settings/`

The user create/edit paths accept a temporary password and a role code. Role codes are UPPERCASE (`OWNER`, `MANAGER`, `CASHIER`, `BARMAN`). `PATCH /settings/` is a partial update and records `updated_by`. Every endpoint here is Owner-only enforced through `accounts.manage_users` / `accounts.manage_roles` / `accounts.manage_settings` permission classes; a Manager receives a plain 403 with no side effects.

## Non-Negotiable Rules

- `ROLE_MATRIX` in `backend/apps/accounts/permissions.py` is the only role-to-permission mapping. Views use `user.has_perm()` through permission classes; never branch on `user.role`.
- Every endpoint is private by default, session-authenticated, JSON-only, versioned, and uses `BarkotPagination` for list responses. The automatic contract suite discovers mounted endpoints.
- Expected domain failures raise `BARKOTDomainError` subclasses. The API envelope is `{"error": {"code", "message", "details"?}}`.
- Money is Decimal/NUMERIC and explicitly ETB. Never use floats.
- State-changing services validate first, run atomically, write all linked domain/ledger records, audit the event, then return.
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
- API mounting: `backend/config/api_urls.py`
- Contract tests: `backend/tests/api/test_contract.py`
- C1 acceptance tests: `backend/apps/finance/tests/test_finance_api.py`
- C3 acceptance tests: `backend/apps/inventory/tests/test_inventory_api.py`
- C4 acceptance tests: `backend/apps/reports/tests/`
- C5 acceptance tests: `backend/apps/accounts/tests/test_admin_api.py`

### Frontend

- Shared typed client: `frontend/src/lib/api/client.ts`
- Finance client/screens: `frontend/src/lib/api/finance.ts`, `frontend/src/features/finance/`
- Inventory client/screens: `frontend/src/lib/api/inventory.ts`, `frontend/src/features/inventory/`
- Payroll client/screens: `frontend/src/lib/api/payroll.ts`, `frontend/src/features/payroll/`, `frontend/src/app/(app)/payroll/`
- Reports client/screens: `frontend/src/lib/api/reports.ts`, `frontend/src/features/reports/`, `frontend/src/app/(app)/reports/`
- Settings client/screen: `frontend/src/lib/api/admin.ts`, `frontend/src/features/settings/settings-page.tsx`, `frontend/src/app/(app)/settings/`
- Product list contract: `frontend/src/lib/api/products.ts` and `backend/apps/products/serializers.py`
- Protected finance routes: `frontend/src/app/(app)/finance/`
- Protected inventory routes: `frontend/src/app/(app)/inventory/`
- Stubbed E2E: `frontend/tests/e2e/`
- Live E2E: `frontend/tests/live/` — shared throttle-aware `signIn` in `frontend/tests/live/signin.ts` (repo `report > payroll > b5-sale > settings` alphabetical order, one worker)

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

Last verified result after C5: **1203 passed** (915 after C3, +288 across C2/C4/C5), with 45 known deprecation warnings from `drf_spectacular` on the current Python runtime. OpenAPI validation had 0 errors and 5 enum-name warnings (three `status` collisions, `PaymentStatusEnum`, and `CodeEnum` — the last from the roles endpoint; all cosmetic).

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

Last verified after C5: **83 Vitest tests**, **30 stubbed Playwright tests**, and **8 live Playwright tests** passed. The live run required these local-only overrides because the checked-in harness defaults still use historical `barket` names while this Compose volume uses `barkot`:

```powershell
$env:E2E_DB_NAME='barkot_e2e'
$env:E2E_DB_USER='barkot'
$env:E2E_DB_PASSWORD='barkot'
npm run test:e2e:live
```

Do not casually rename the harness or seed safety strings; they are covered by tests and may reflect CI naming. Treat the local override and the committed CI configuration as separate concerns.

## Known Gaps and Decisions

- B5's original browser income claim was blocked before C1 because no finance read existed. C1 now exposes the read. Decide explicitly whether to amend the roadmap status or add a B5 browser assertion; do not mark it silently.
- C3 has backend HTTP acceptance tests but no inventory-specific Playwright scenario yet. Existing stubbed/live suites pass; D2 eventually requires browser coverage of the normative scenarios.
- The frontend has some existing non-blocking lint warnings in older product/sales files when running full lint without `--quiet`; do not mix them up with new errors.
- Open client decisions remain: physical count frequency/closing time, payroll additions/overtime/absence, deduction/statutory calculations, fiscal/e-invoicing, domain availability, VPS, and payment method.
- The repository and product are named `barkot`; some older internal strings and live E2E defaults say `barket`. Verify before changing any such string because some are intentional test guards and some are stale naming.

## Safe Next Action

Before writing dashboard code:

1. The dashboard shell already exists at `frontend/src/app/(app)/dashboard/`; verify its current placeholder and what API client and screen conventions Finance/Inventory/Payroll established.
2. Add a failing acceptance test for the chosen figures (e.g. finance balance + expense total, latest payroll run state + net pay, top products by revenue from sales) so the endpoint is forced to reconcile to authoritative sources.
3. Add the viewset/serializer and mount it in `backend/config/api_urls.py` using `docs/ADDING_AN_ENDPOINT.md` — the contract suite will discover it automatically.
4. Add the typed client under `frontend/src/lib/api/dashboard.ts` and the screen under `src/features/dashboard/` behind the route group.
5. Prove the displayed figures reconcile to the underlying transactions before considering C6 complete.
6. Run the full gates and commit only when the worktree contains the intended phase changes.
