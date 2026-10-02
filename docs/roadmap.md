# Barkot Build Roadmap

- **Status:** Active
- **Last updated:** 2026-09-29
- **Reference spec:** BARKOT-SAS-001 v1.0.0 (`docs/architecture/Barkot_Software_Architecture_Specification.docx`)
- **Deviation log:** [ADR-0004](architecture/ADR/ADR-0004-phase-0b-vertical-slice.md)

This is the build plan for the remaining work, expressed as tasks that each end in a command that must
pass. It is written per task rather than per date: a task is done when its gate is green, and the
order reflects dependencies, not a calendar.

## How the phases relate to the spec

Spec §28 defines seven phases (0–6) as a horizontal, domain-by-domain sequence. The work completed so
far did not follow that shape, and this roadmap is organised around the sequence actually being built.
The mapping is:

| Spec §28 phase | Where it stands | Where this roadmap covers it |
| --- | --- | --- |
| 0 — Environment + design baseline | Complete (0A) | — |
| 0B — domain foundation (this project's own label) | Complete | — |
| 1 — Auth + users + products | Models, services and role matrix done; no API, no UI | Phase A (auth), Phase B (products vertical) |
| 2 — Sales + inventory | Models and services done; no API, no UI | Phase B (sales vertical), Phase C (C3) |
| 3 — Finance | Models and services done; no API, no UI | Phase C (C1) |
| 4 — Payroll | Models and services done; no API, no UI | Phase C (C2) |
| 5 — Hardening | Not started | Phase D |
| 6 — Optional integrations | Not started, externally blocked | Phase E |

**The important consequence:** the *backend* work of spec Phases 1–4 is already complete. What remains
for those phases is the API surface, the frontend, and the hardening — not the domain modelling. The
spec must not be read as "Phases 1–4 still ahead".

## Where the project actually stands

Measured, not assumed:

| Layer | State |
| --- | --- |
| Domain models | 9 apps with models, 11 migrations applied |
| Service/use-case layer | 4 apps with services (sales, inventory, finance, payroll) |
| Tests | 508 passing — domain invariants, permission matrix, production settings guards, error envelope, API base, pagination, signed-out access sweep, idempotency keys and receipt allocation under real thread contention |
| Static analysis | mypy clean over 135 files, ruff clean |
| **API endpoints** | **2 health probes, a versioned API root, and an OpenAPI schema with one documented path (`/api/v1/`). No business endpoints yet — that is A4.** |
| **Frontend** | **24 files, all shell. No API client, no auth, no data. 7 feature directories empty.** |
| `reports` app | `apps.py` only |
| `audit` app | Model and `record()` only; not yet written to by any endpoint |
| Audit coverage | Services call `AuditLog.record()`, so most state changes are already audited |

The backend's middle is built. Its two ends — the API that exposes it and the UI that consumes it —
are untouched. That is most of the remaining product.

## The shape of every phase

Each phase runs the same loop: **specify → test → implement → verify → deploy-check.**

1. **Specify.** The acceptance criteria are written into a failing test or contract case first.
2. **Test.** The specified behaviour is expressed in the project's existing suites (pytest, vitest,
   Playwright), not in ad-hoc verification.
3. **Implement.** The smallest change that turns the test green.
4. **Verify.** The full local gate set passes (§ Verifying a task).
5. **Deploy-check.** Nothing ships to a shared environment in these phases; deployability is proven in
   Phase D.

## Verifying a task

Every task below names its gate. These are the commands; a task is not complete until they pass.

Backend gates:

```powershell
cd backend
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe .
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -m pytest -q
```

Frontend gates:

```powershell
cd frontend
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
npm run test:e2e
```

Database access on this machine requires `DJANGO_DB_PORT=5433` and the password from `.env`. See
[Getting started](../README.md#getting-started). CI runs the equivalent of these on both stacks
(`.github/workflows/ci.yml`).

## Phase A — API layer and session authentication

**Outcome:** the backend is reachable over HTTP, and a real user can log in and be authorised. This is
the first point at which anything built so far can be seen working.

Authentication is **session-based, not JWT** (spec §9.1). The browser receives an opaque session ID in
an `HttpOnly` cookie; there is no token to store, no signing key to manage, and no external identity
provider. `DJANGO_SECRET_KEY` is generated locally and is already guarded in
`config/settings/prod.py`.

| # | Task | Gate that proves it |
| --- | --- | --- |
| ~~A0~~ | Run all 7 CI gates against the real code; fix what fails | `mypy .`, `npm run build`, Playwright all green |
| ~~A1~~ | Fix `DJANGO_DEBUG` being dead config (`dev.py` and `prod.py` both assign `DEBUG` unconditionally) | The variable is gone from the repo; `dev` always sets `DEBUG=True` and `prod` always sets `DEBUG=False`, and neither can be overridden by the environment |
| ~~A2~~ | API base: versioning, error envelope, pagination wiring, OpenAPI integration | Schema `paths:` is no longer empty; every API failure returns `{"error": {"code", "message"}}`; an oversized `page_size` is capped rather than silently honoured |
| ~~A3~~ | **Contract suite skeleton** — parameterised rules every endpoint must satisfy | Fails when a deliberately non-compliant endpoint is added |
| ~~A4~~ | `/auth/csrf`, `/auth/login`, `/auth/logout`, `/auth/me` | Login as each of the 4 roles; wrong password returns 400, not 500; logout invalidates the session |
| ~~A5~~ | Login rate limiting (spec 9.3): 5 attempts a minute per client address, counted in the database so Gunicorn workers share one budget. Login only, since no sensitive business endpoint exists yet; `LoginRateThrottle` is reusable for them | 6th attempt from one IP returns 429 |
| ~~A6~~ | Session timeout, forced change for temporary passwords, `last_login_ip` | Expired session returns 403; temporary password forces a change |
| ~~A7~~ | `create_owner` management command (mirrors `bootstrap_roles`) | Creates a working Owner; the password is not logged |
| ~~A8~~ | DRF permission classes bound to `ROLE_MATRIX` | A Cashier cannot approve payroll (spec §23.1) |
| ~~A9~~ | Security tests: unauthenticated access and role bypass — a live sweep that discovers every route from the contract engine and derives public ones from its exemptions, so an endpoint added without protection fails | Every protected route answers a sessionless request with 401 and a challenge header; the role dimension is wired and fires automatically once a business endpoint declares one |
| A10 | ~~`Idempotency-Key` on write endpoints~~ — delivered at the **service** layer instead, since Phase A has no business endpoint to carry a header and inventing one would contradict A2–A4; ~~fix the `next_sale_reference()` count-then-insert race~~ — the count is now taken under a transaction-scoped `pg_advisory_xact_lock` | The same key twice creates one sale, not two; concurrent references do not collide. Both proved by tests that fail with the mechanism removed, not only by green tests |

**Phase A exit criteria:** a user can log in through HTTP, an unauthorised user receives 401/403
everywhere, and the OpenAPI schema describes real endpoints.

**Phase A is otherwise complete, and the third criterion cannot be met from here.** The first two
hold and are tested (A4, A9). The third is not yet true: the schema describes the six auth and root
paths, and there is no business endpoint to describe. It becomes satisfiable the moment Phase B adds
one, and it cannot be made true inside Phase A without inventing a route purely so that the schema
has something to describe — which is the A2–A4 pattern this roadmap was written to end. Treat
Phase A as complete with that one criterion carried forward, not as a phase still ahead.

### The contract suite, and why it is here rather than in Phase C

Delivered in `backend/tests/api/contract.py`. Every rule is a plain function from an `Endpoint` to a
problem string, and every rule runs against every endpoint discovered from the live URLconf — so an
endpoint added in Phase C is checked without anyone remembering to write a test for it. Five rules:
`private_by_default`, `session_auth_only`, `no_browsable_api`, `project_paginator`, `versioned_path`.

Two decisions keep it from decaying:

- **Rules read class attributes, not responses.** No fixtures, no database rows, no guessing what a
  call to a resource that does not exist yet should return. The suite runs in well under a second, so
  nobody is tempted to skip it.
- **Exemptions are declared and checked for necessity.** `ApiRootView` is public on purpose and the
  schema views sit outside the version prefix on purpose; both carry a written reason. A test fails if
  an exemption waives a rule its endpoint would have passed anyway, which is what stops the exemption
  list from widening until nothing is enforced.

The gate was verified by registering a deliberately non-compliant endpoint in the real URLconf and
confirming the suite fails, by moving it outside `/api/v1/` and confirming a different rule fires, and
by widening an exemption and confirming that is caught too.

## `create_owner`, and why the Owner is not a superuser

Delivered in `backend/apps/accounts/management/commands/create_owner.py`. The command exists because
there must be exactly one way to make the first Owner, and `createsuperuser` is the wrong tool three
times over. `accounts.User.role` is non-null and a superuser is created without one, so every login
would fail against the foreign key. More importantly, `is_superuser=True` short-circuits `has_perm`
entirely: the role matrix would stop being the thing that decides what the Owner can do, and a later
edit to it would not apply. The Owner created here holds the whole catalogue *through the matrix*, so
P06 stays the single enforcement point.

The password is never an argument. It comes from a no-echo prompt or from `--password-stdin`, because
an argument is visible in shell history, in `ps` output, and in any process listing for as long as the
command runs, on a machine several people administer. There is deliberately no `--password` flag and no
`DJANGO_OWNER_PASSWORD` variable; both are an argument wearing a disguise, and both end up in a CI log.
`--generate-password` prints once to stdout, which is the only way for a human to learn a secret they
did not choose, and flags the account temporary so A6 forces a change at first login. The test suite
asserts on `caplog`, `stderr`, stdout, and the raw database column, since a leak here is invisible in
normal use — the command works perfectly and the only symptom is a secret sitting in a log.

Two things it refuses by default: a username that already exists, and a *second* Owner without
`--force`. A second Owner is a grant of full authority over payroll and cash, so it has to be asked
for deliberately. `--check` runs as a bare preflight (`manage.py create_owner --check`) and exits
non-zero when an Owner already exists, which is the signal a deployment runbook wants.

Building it surfaced a bug that predates it: `Role.objects` was assigned a bare `RoleQuerySet()`
instance, which does **not** give you a manager carrying that queryset's methods — Django falls back
to a plain `Manager`, so `Role.objects.for_code(...)` raised `AttributeError` and the method was
unreachable. Nothing else called it, so nothing was broken in practice. It is now `RoleManager()`,
built with `from_queryset`, and `test_permissions.py` asserts the manager type so the mistake cannot
come back quietly.

## Phase B — Frontend data layer and one vertical

**Outcome:** one complete flow works end to end in a browser, and it becomes the template for
everything after it.

| # | Task | Gate that proves it |
| --- | --- | --- |
| B0 | Frontend build and Playwright baseline green before any change | `npm run build` and `npm run test:e2e` pass |
| B1 | Typed API client and CSRF handling | A test asserts nothing is written to `localStorage` |
| B2 | Auth context and protected route guard | An unauthenticated visit to `/sales` redirects to `/login` |
| B3 | `/login` page | E2E: enter credentials, land on the dashboard |
| B4 | **Golden vertical** — product list and create | E2E plus the full contract suite; this is the reference implementation |
| B5 | Sales → inventory vertical | E2E §23.1: a Cashier records a sale, stock decreases exactly once, income increases |
| B6 | `docs/ADDING_AN_ENDPOINT.md`, written from what B4 and B5 actually did | A new domain can be built by following it without asking |

B4 is deliberately the *first* domain rather than the most important one. It is small enough to
finish quickly, which makes it the cheapest possible place to discover that the underlying pattern is
wrong.

## Phase C — Remaining domains

Each task is: viewset, serializer, filters, frontend screen, E2E scenario, contract-suite cases.
Each must be green before the next begins, so a regression is caught in the task that caused it.

| # | Domain | Gate that proves it |
| --- | --- | --- |
| C1 | Finance — expenses, balance | E2E plus contract suite; balance reconciles to source transactions |
| C2 | Payroll — employees, runs, deductions | E2E §23.1: Manager generates a monthly run, deduction reason is captured, net pay reconciles |
| C3 | Stock — receive, count, variance, breakage | E2E §23.1: Barman receives stock; Manager completes a count and the adjustment requires permission |
| C4 | Reports — date filters and export | E2E for each report |
| C5 | Users, roles, settings | Owner-only access enforced; a Manager is refused |
| C6 | Dashboard summary | Displayed figures reconcile to the underlying transactions |

**Why C is not expected to slip.** The data modelling and business rules for all six domains are
already written and tested (70 tests, including 19 domain invariants). The remaining work is
application of a pattern proven in B4, not new design. The two failure modes that normally make a
"thin CRUD over existing services" phase slip were checked in advance:

- Every model already declares `Meta.ordering`, so list endpoints are deterministic and paginate
  without an N+1 surprise.
- Services return model instances or dataclasses (`complete_sale() -> Sale`,
  `finance_balance() -> FinanceBalance.as_dict()`), so there is a clean, consistent seam to
  serialise at.

## Phase D — Hardening and production readiness

| # | Task | Gate that proves it |
| --- | --- | --- |
| D0 | Rate limiting on all sensitive endpoints (§9.3) | Load test exceeds the configured limit and receives 429 |
| D1 | Audit coverage: every state-changing endpoint writes `AuditLog` (P06) | A test per endpoint asserts the audit row |
| D2 | Full E2E suite covering all five §23.1 scenarios | Suite green in CI |
| D3 | Automated backups | **A restore drill**: restore into a scratch database and reconcile |
| D4 | Production runbook | A second person can deploy and roll back from the document alone |
| D5 | Observability baseline (§24): request ID, user ID in logs, alerting on 5xx and health | Alert fires in a test environment |
| D6 | Deployment rehearsal on a target host | Full stack starts from `docker compose.prod.yml` with real secrets |

D3's restore drill is the item most often skipped and the one that matters most: an untested backup is
a hypothesis.

## Phase E — Optional integrations

Deferred, and externally blocked. No engineering should start until the client resolves the open
questions in `docs/business/client-decisions.md`:

- Chapa / payment provider — spec §16, §28 Phase 6
- Fiscal and e-invoicing — spec §30 item 8
- Email — spec §28 Phase 6
- Object storage and file upload — explicitly out of scope for this version (CD-04)
- Async jobs (Redis/Valkey + Celery) — only when a real async workload exists (P07)

`backend/apps/integrations/` remains an empty boundary marker (P08) so a provider can be added without
reshaping `sales` or `finance`.

## Open questions that affect the plan

Carried from spec §30 via `docs/business/client-decisions.md`. None blocks Phases A–C:

| # | Item | Affects |
| --- | --- | --- |
| 4 | Stock count frequency and whether a formal closing time exists | D1, C4 reporting boundaries |
| 5 | Payroll addition, overtime and absence rules | C2 |
| 6 | Payroll deduction approval policy and statutory calculations | C2 |
| 8 | Fiscal / e-invoicing technical requirements | E |
| 9, 10 | Commercially permitted VPS provider and ETB payment method | D6, E |

Stock count frequency (item 4) is the only one with a design impact rather than a configuration
impact: a closing time implies business-day cut-off logic in reports. That decision should land
before C4.
