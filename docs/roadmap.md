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

Measured, not assumed (last verified after D0):

| Layer | State |
| --- | --- |
| Domain models | 9 apps with models, 11 migrations applied |
| Service/use-case layer | 8 apps with services (accounts, dashboard, finance, inventory, payroll, products, reports, sales) |
| Tests | 1244 backend passing — domain invariants, permission matrix, production settings guards, error envelope, API base, pagination, signed-out access sweep, rate-limit configuration and the write-throttle load test, idempotency keys and receipt allocation under real thread contention, plus per-domain acceptance tests |
| Static analysis | mypy clean over 179 files, ruff clean |
| **API endpoints** | **Phases A–C complete: auth, products, sales, finance, inventory, payroll, reports, users/roles/settings and the dashboard, behind an OpenAPI schema that validates with 0 errors** |
| **Frontend** | **Typed client and protected route group with a screen per domain through C6; 83 Vitest, 34 stubbed and 14 live Playwright tests green** |
| `reports` app | C4 — financial, inventory and payroll reports with CSV export |
| `audit` app | Model and `record()`; written by services, D1 asks for per-endpoint coverage |
| Audit coverage | Services call `AuditLog.record()`, so most state changes are already audited |

Phases A–C are built and proven end to end. Phase D — hardening and production readiness — is done
through D5; D6's local rehearsal passed and its target-host milestone is blocked on client decisions.
Phase E, optional integrations, is externally blocked.

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

Two things it refuses: a username that already exists, and a *second* Owner, unconditionally — there
is no `--force`. A second Owner is a grant of full authority over payroll and cash, and Barkot has
exactly one, so the command checks for an existing Owner inside the same transaction as the insert,
behind a `SELECT … FOR UPDATE` lock on the Owner role, and a PostgreSQL constraint trigger
(`0002_single_owner`) refuses a second one behind that. The account-admin service refuses one too,
returning a clean `409 owner_exists` rather than a database error. `--check` runs as a bare preflight
(`manage.py create_owner --check`) and exits non-zero when an Owner already exists, which is the
signal a deployment runbook wants.

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
| ~~B0~~ | Frontend build and Playwright baseline green before any change | `npm run build` and `npm run test:e2e` pass |
| ~~B1~~ | Typed API client and CSRF handling | A test asserts nothing is written to `localStorage` |
| ~~B2~~ | Auth context and protected route guard | An unauthenticated visit to `/sales` redirects to `/login` |
| ~~B3~~ | `/login` page | E2E: enter credentials, land on the dashboard |
| B4 | **Golden vertical** — product list and create | E2E plus the full contract suite; this is the reference implementation |
| B5 | Sales → inventory vertical | E2E §23.1: a Cashier records a sale, stock decreases exactly once, income increases |
| B6 | `docs/ADDING_AN_ENDPOINT.md`, written from what B4 and B5 actually did | A new domain can be built by following it without asking |

B4 is deliberately the *first* domain rather than the most important one. It is small enough to
finish quickly, which makes it the cheapest possible place to discover that the underlying pattern is
wrong.

### B1: the CSRF token is read from the cookie, not from the response body

`CsrfResponseSerializer` returns the token in the response body, and its `help_text` suggests a client
may keep it in memory and never read the cookie. That is the wrong choice here, for a reason that only
shows up once someone logs in: `django.contrib.auth.login()` calls `rotate_token()`, so the token a
client cached before signing in is stale the instant it does, and its next write is refused with 403.
The same happens on logout. The browser's copy of the cookie is the one thing Django itself rewrites,
so `client.ts` reads `document.cookie` at send time on every unsafe request and caches nothing. A test
asserts that a rotated cookie is picked up, and a second one that a cold client bootstraps a token by
calling `/auth/csrf/` first.

Two smaller decisions in the same file are recorded in its header comment, and both exist because the
alternative is a bug rather than a style question: unsafe requests always carry a JSON body, because
Django's CSRF check parses the body for a form token and rejects `multipart/form-data` with 415; and a
response that is not the error envelope still becomes a typed `ApiError`, because A9 found the browsable
API serving an HTML login page for an unauthenticated request.

### B2: protection is a place a page lives, not a check a page remembers

The 17 application routes moved into an `(app)` route group and `/login` sits in `(public)`. Route
groups do not appear in URLs, so every `href` in `nav.ts` is unchanged — but the consequence is the
point. A page is protected by being *in* the application group, so the next person to add a screen
gets a guard by placing it in the directory that already means "signed in". The alternative, a guard
each page opts into, is the A2–A4 pattern again: protection that has to be remembered is protection
that will be forgotten.

The guard renders nothing at all until the session is known, rather than rendering and redirecting
once the answer arrives. A cashier who is not signed in would otherwise see a frame of the screen
they are not allowed to open — ugly, and a small disclosure of what exists.

There are four states, not two, and the fourth is the one that matters: `unavailable` is not
`anonymous`. A 500 or a dead network must not be reported as "your session has expired, please sign
in", because signing in again will not fix it and the user leaves believing their password is the
problem. Only `not_authenticated` — the code the API reserves for exactly that — means signed out, and
everything else gets a retry button instead of a redirect. Both directions are asserted in E2E
against a stubbed 502, because the quiet version of this bug is a support call.

### B2 found that `npm start` was serving no JavaScript

`next build --output standalone` emits a self-contained server but deliberately excludes the client
bundle; `Dockerfile.frontend` copies `.next/static` into the image. `npm start`, and the Playwright
`webServer` that borrowed its command, ran `node .next/standalone/server.js` on a tree with no
`.next/standalone/.next/static` in it — so every page loaded its HTML and nothing else. No hydration,
no client component, no fetch.

This was invisible for as long as the E2E tests asserted only server-rendered HTML, which is all they
did at B0: a redirect, a title, a link count, a heading. Those pass against a page that cannot
execute a line of script, so the suite read as browser coverage while covering a static file. B2's
gate failed on arrival for exactly this reason — the guard was mounted correctly and simply never ran.

`scripts/prepare-standalone.mjs` now performs the copy the Dockerfile already performed, and both
`npm start` and Playwright go through it, so the thing under test is the same artifact production
runs. Worth stating plainly: before this, three green Playwright tests were measuring far less than
they appeared to.

### B5: the sale screen had never been opened by a test

**B5 stays open.** Two of its three claims are now proven in a real browser; the third cannot be,
and closing that gap is a decision rather than a task. The detail is below.

The gate for B5 is a Cashier's browser, this Django and this Postgres. It took until this task for
that sentence to mean anything, because until now every Playwright spec answered the API itself.

The first run of a real browser against the real backend found a defect that 16 stubbed specs, 57
vitest tests and 714 backend tests had all passed without noticing: **the New Sale screen crashed on
load, for every user, every time.** `fieldErrors` is a sparse record — it starts as `{}` and only
gains keys when the API answers with field-level errors — and four places in
`frontend/src/app/(app)/sales/transactions/new/page.tsx` read `fieldErrors[key].length` directly
instead of through the `?? []` the rest of that file already used. First render, before anyone had
typed anything, so React threw and the error boundary took over.

Nothing caught it because the stubbed suite had never visited the page, and no unit test covered it.
A stub cannot catch this class of thing at all: it was not the frontend disagreeing with the
backend, it was the frontend disagreeing with itself.

The live specs now cover one story in order, because each step depends on the last:

1. a wrong password, refused by Django's own authenticator, arriving as a serializer
   `ValidationError` under `non_field_errors` — the same shape the stub asserts, except Django
   produced it;
2. a Cashier signs in with a real session, sees an empty till, records a three-unit sale, and the
   stock ledger moves **exactly once** — read back over HTTP with the cashier's own cookie, because
   a screen agreeing with itself is not evidence;
3. that Cashier's void is a real `403` from a real permission and the sale still stands, and then a
   Manager's void is a real `204` and the stock is back to 40.

That "exactly once" is checked by mutation, not by inspection: recording the outbound
`StockMovement` a second time makes the browser spec fail with 34 units on the shelf instead of 37,
and makes three backend vertical tests fail. The same check on the seed command's reset guard — the
thing standing between a mistyped `DJANGO_DB_NAME` and an emptied working database — fails four
tests when the guard is disabled.

**Three harness decisions, each of which cost something to get wrong.**

*A port of its own.* Django runs on 8010, not 8000, because a developer usually has a server on 8000
pointed at their working database and Playwright reuses an existing server outside CI. Reusing that
would sell the business's real books during a test run.

*A database of its own, and a seed command rather than a fixture.* pytest builds a test database and
tears it down; a browser, a `runserver` and a Next proxy all need one database alive at the same
time, outside pytest's lifecycle. So `backend/apps/core/management/commands/seed_e2e.py` creates it
and refuses to `flush` anything whose name does not end in `_e2e`. The fixtures address everything by
constant and print those constants as JSON, so the ids and passwords the specs use live in exactly
one place instead of being copied into TypeScript and left to drift.

*One origin.* The browser stays on `127.0.0.1:3000` and Next forwards `/api/v1/` to Django, exactly
as Nginx does in production, so the session and CSRF cookies behave as deployed and no CORS
configuration was needed. This required `next.config.ts` to grow an opt-in for production builds:
the proxy used to be development-only, and `next start` is a production build. `API_PROXY_ENABLED=1`
is now that ask, so a deployment that has not asked for a proxy still has none.

**The third claim is not reachable from a browser yet, which is why B5 is not struck.**
"E2E §23.1: a Cashier records a sale, stock decreases exactly once, income increases" — the first
two are asserted in `tests/live/b5-sale.spec.ts` against a real session and a real database. The
third is not, and not because it was overlooked: **there is no API from which a browser could read
income.** The finance app has models and services and no viewset; `config/api_urls.py` routes auth,
products and sales only. The dashboard, which the specs land on after signing in, fetches nothing.

The claim is not unproven so much as unobservable *in a browser*. It is asserted over HTTP in
`backend/apps/sales/tests/test_sale_vertical.py`, which reads `finance.services.income_by_method`
and checks it is `0.00` before a sale, the exact total after one, back to `0.00` after a refused sale,
and back to `0.00` after a void — the same service any future endpoint would call. That is real
evidence about income, and it is not E2E.

Two honest ways to close this, and the choice is not mine to make:

1. **Add a read-only income endpoint and assert it in the browser.** Small, and it makes the gate
   literally true. But it is new public API surface, and the roadmap already assigns finance reads to
   **C1** and displayed figures to **C6**. Doing it here means doing a slice of C1 inside B5.
2. **Accept that "income increases" is proven at the HTTP-and-service layer, not the browser layer**,
   and record that as the gate's wording. Defensible — the vertical's own E2E story is about the
   sale, the stock ledger and the permission, none of which income is — but it *is* a weakening, so it
   should be said out loud rather than done quietly.

Until one of those is chosen, B5 stays unmarked. Marking it complete on two of three claims would be
the exact failure this gate exists to prevent.

**A finding this phase did not fix.** The sales screen offers a `Voided` status filter, and
`StatusBadge` knows how to render `VOIDED`. Neither can ever appear: `SaleViewSet`'s queryset is
`Sale.objects`, and `VoidableManager` excludes voided rows from the default queryset by design — so
`?status=VOIDED` returns nothing, always. The design is deliberate and documented, and a voided sale
correctly leaves the list a cashier reconciles against. But a filter that cannot match is a control
that lies to the user, and a Manager who needs to see what was voided last week currently cannot.
Deciding whether the API should list voided sales on request is a product question — "a void is a
reversal, not a sale" and "an audit record a manager can inspect" are both defensible — so it is
recorded here rather than quietly changed.

### The stubs stayed, and they are not the weaker half

Worth being explicit, because replacing them would have been the obvious move and the wrong one. A
real server cannot be asked to produce a dead backend, a `502`, a throttled sign-in or a forced
password change on demand, and those are exactly the states where the frontend's behaviour matters
most — a `502` that reads as "session expired" sends a cashier to a login screen where the correct
password also fails, and they conclude they are locked out. So `tests/e2e/` keeps its stubs and
`tests/live/` adds the half that installs none.

One thing that split taught me, and it is not obvious: **`page.route` intercepts the browser's
requests and nothing else.** An `(app)` page's server-side render still asks the real origin for
`/auth/me/`. Running both projects in a single Playwright invocation meant every stubbed navigation
paid a real database round trip, and four workers doing that at once pushed four redirect assertions
past their timeout — a failure caused by the harness and reported as a behavioural one, which is the
more expensive mistake of the two. `npm run test:e2e` now runs the projects as two invocations. It
costs an extra production build and buys back three things: the stubbed suite is honest about having
no backend, it needs neither Postgres nor Python, and CI gets two separately attributable results.

## Phase C — Remaining domains

Each task is: viewset, serializer, filters, frontend screen, E2E scenario, contract-suite cases.
Each must be green before the next begins, so a regression is caught in the task that caused it.

| # | Domain | Gate that proves it | Status |
| --- | --- | --- | --- |
| C1 | Finance — expenses, balance | E2E plus contract suite; balance reconciles to source transactions | Done |
| C2 | Payroll — employees, runs, deductions | E2E §23.1: Manager generates a monthly run, deduction reason is captured, net pay reconciles | Done |
| C3 | Stock — receive, count, variance, breakage | E2E §23.1: Barman receives stock; Manager completes a count and the adjustment requires permission | Done |
| C4 | Reports — date filters and export | E2E for each report | Done |
| C5 | Users, roles, settings | Owner-only access enforced; a Manager is refused | Done |
| C6 | Dashboard summary | Displayed figures reconcile to the underlying transactions | Done |

`ENGINEERING_HANDOFF.md` carries the per-phase list of what shipped and the verified gate counts.

**Why C was not expected to slip.** The data modelling and business rules for all six domains were
already written and tested (70 tests, including 19 domain invariants). The remaining work was
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
| ~~D0~~ | Rate limiting on all state-changing endpoints (spec §9.3): every unsafe method on every endpoint, 60 a minute per client address, installed as DRF's `DEFAULT_THROTTLE_CLASSES` so a new endpoint cannot be exempt by omission. Reads are never throttled; login keeps its stricter 5/m | Load test exceeds the configured limit and receives 429 |
| ~~D1~~ | Audit coverage: every state-changing endpoint writes `AuditLog` (P06). A completeness test enumerates the discovered unsafe surface and fails if a method/path has no scenario; each of the 31 scenarios then posts through the real view and asserts exactly one new row with the right action, object type, actor, object id and summary. Writing it found three silent gaps - product and category `perform_create` and `set_price` all logged `actor=None` - and confirmed sales mutations are unreachable rather than unlogged: `http_method_names` removes them from DRF's router, so the audit surface and the discovered surface cannot drift apart | A test per endpoint asserts the audit row |
| ~~D2~~ | Full E2E suite covering all five §23.1 scenarios | Suite green in CI |
| ~~D3~~ | Automated backups | **A restore drill**: restore into a scratch database and reconcile |
| ~~D4~~ | Production runbook | A second person can deploy and roll back from the document alone |
| ~~D5~~ | Observability baseline (§24): request ID, user ID in logs, alerting on 5xx and health | Alert fires in a test environment |
| D6 | Deployment rehearsal on a target host | Full stack starts from `docker compose.prod.yml` with real secrets |

D3's restore drill is the item most often skipped and the one that matters most: an untested backup is
a hypothesis.

D6 held a local rehearsal on 2026-10-08 (stack up from `docker compose.prod.yml` with generated secrets,
migrate applied, `/health/live` + `/health/ready` 200, owner login 200, `X-Request-ID` present, nginx
`nginx -t` clean, `zone=login` wired). The milestone rehearsal on a real Ubuntu VPS remains open:
it is blocked on the client decisions for a commercially permitted VPS provider and domain (9/10).

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
