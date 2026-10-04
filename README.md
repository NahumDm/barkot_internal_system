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

| Area                           | State                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Backend (Django 5.2 LTS + DRF) | 9 domain apps with models, 4 with service layers, 10 migrations applied                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Tests                          | 508 passing – domain invariants, permission matrix, permission classes cross-checked against the matrix over every role and permission, production config guards, error envelope, API base, pagination, endpoint contract rules, `create_owner` bootstrap, session auth endpoints, login rate limiting, session timeout, forced password change, a live signed-out access sweep over every registered route, and idempotency keys and receipt allocation under real thread contention                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| Static analysis                | mypy clean (130 files, `mypy .`), ruff clean                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Authentication                 | Custom user, 4-role permission matrix, session/CSRF settings wired. One DRF permission class per capability in `apps/accounts/permissions.py`, each resolving through `user.has_perm()` so the matrix stays the single enforcement point; a view writes `permission_classes = [IsAuthenticated, CanApprovePayrollRun]`. Payroll approval is Owner-only, deliberately withheld from the Manager who generates the run (spec 23.1). `manage.py create_owner` creates the first Owner. Session auth is live: `/auth/csrf`, `/auth/login`, `/auth/logout`, `/auth/me`, `/auth/change-password`. Login is rate limited to 5 attempts a minute per client address, counted in the database so the budget is shared between Gunicorn workers. Sessions idle out after a configurable timeout (default 8 hours, Owner setting) and are answered `403 session_expired`. An account flagged `is_temporary_password` can reach only `/auth/me`, `/auth/logout`, `/auth/csrf` and `/auth/change-password` until it sets a new one; everything else answers `403 password_change_required`. |
| **API**                        | **Versioned under `/api/v1/`, one error envelope for every failure, pagination with a hard cap, the five session auth endpoints, rate limiting on login, and an OpenAPI schema that documents every one of them with its security scheme. No business endpoints yet.**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **Frontend**                   | **Shell only. 24 files, no API client, no auth, 7 feature directories empty.**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `reports` app                  | `apps.py` only                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Audit                          | `AuditLog.record()` called from services; no API to read it                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Contract suite**             | **`tests/api/contract.py` — 5 rules every registered endpoint must satisfy, with declared exemptions. A new endpoint is checked automatically.**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **Owner bootstrap**            | **`manage.py create_owner <username>` — the password is read from a no-echo prompt or stdin, never an argument. `--generate-password` prints once; `--check` is a bare preflight.**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| Docker / Nginx / Compose       | Dev + prod compose, multi-target Dockerfiles, host Nginx config                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| CI                             | `.github/workflows/ci.yml` — the 7 §22.2 gates on both stacks                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| Docs                           | ADRs 0001–0004, client decisions, roadmap                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

### How this maps to spec §28

Spec §28 lays out seven phases as a horizontal, domain-by-domain sequence. The work so far was built
as one vertical slice instead, so §28 no longer describes the repository literally. The important
part:

**The backend work of spec Phases 1–4 is complete** — models, business rules and services for auth,
users, products, sales, inventory, finance and payroll. What remains for those phases is the API, the
frontend, and hardening. Recorded in
[ADR-0004](docs/architecture/ADR/ADR-0004-phase-0b-vertical-slice.md).

| Spec §28 phase                    | State                                         |
| --------------------------------- | --------------------------------------------- |
| 0 — Environment + design baseline | Complete                                      |
| 1 — Auth + users + products       | Domain layer complete; API and UI outstanding |
| 2 — Sales + inventory             | Domain layer complete; API and UI outstanding |
| 3 — Finance                       | Domain layer complete; API and UI outstanding |
| 4 — Payroll                       | Domain layer complete; API and UI outstanding |
| 5 — Hardening                     | Not started                                   |
| 6 — Optional integrations         | Not started; blocked on open client questions |

Architecture decisions are recorded as **ADRs** in `docs/architecture/ADR/`. The BARKOT-SAS-001 Word
spec is author-maintained; deviations are noted in the ADRs for the next (v1.1.0) spec revision.

## Before production

- [ ] **Confirm `DJANGO_TRUSTED_PROXY` is set for the production deploy.** Login rate
      limiting (5/minute per address) keys on the client address. Behind Nginx that
      address only reaches Django in `X-Forwarded-For`, so the variable decides whether the
      limit works or silently collapses. It is off by default because the header is
      written by whoever sent the request; trusting it unconditionally would let an
      attacker pick a fresh bucket per attempt and guess a password forever.
      `docker-compose.prod.yml` defaults it to `true`, which is correct for that stack.
      If the backend is ever deployed without it - bare `gunicorn`, a different proxy, or
      any non-Compose path - set it explicitly there. Wrong in the other direction is worse
      than it looks: the limit still runs, but every client behind the proxy shares the
      proxy's address as its bucket, so one user's mistyped password locks out everyone.
      Verify by making several failed logins from two different addresses and confirming
      each address gets its own 5-attempt budget before real users hit the endpoint.

## Bugs that changed the design

Three defects found while building A6 (session timeout, forced password change). All
three failed quietly - none produced a loud failure that would have been noticed before
release - which is why they are written down here rather than left in the diff. If any
of these symptoms appear in production, they are the same bugs.

### 1. Reading `request.user` inside authentication recursed until the stack limit

`django.contrib.auth.logout()` reads `request.user` to decide whether anyone is signed
in. On a DRF `Request`, `user` is a **property that performs authentication on access**.
Calling `logout()` from inside the authenticator therefore restarted the authenticator
that called it, and every one of those calls started another.

What it looked like from outside: an idle timeout returned **500** with a
`RecursionError` in the log, on every session that actually expired. The 403 the endpoint
was written to return never happened, so the feature would have looked broken rather than
absent.

The design now avoids the trap entirely: `apps.accounts/sessions.py::end_session` flushes
the session and deletes the row directly instead of calling `logout`. Same effect, no read
of `request.user`.

The rule to take from it: **never call code that touches `request.user` from inside
`authenticate()`.** That includes `logout()` and anything that wraps it. Pass the already
resolved user down as an argument instead - which is why `enforce_session_rules()` takes
`user` as a parameter rather than reading it back off the request.

### 2. The password policy raised the wrong exception, so no password was ever rejected

`django.contrib.auth.password_validation` has **no** `PasswordValidationError` attribute
in Django 5.2. `validate_password()` raises `django.core.exceptions.ValidationError`. The
`except` clause named the non-existent attribute, so it raised `AttributeError` _while
handling a rejection_.

What it looked like from outside: every weak or disallowed password returned **500**
instead of **400**. `MinimumLengthValidator`, `UserAttributeSimilarityValidator`,
`CommonPasswordValidator` and `NumericPasswordValidator` were all still running - they
raised correctly - but the refusal was converted into an unhandled error on the way out.
The policy was not weakened, it was unusable: nothing could be rejected without a server
error. A client would have shown the user a generic failure for a password the server had
just told it was too short.

Now caught as `django.core.exceptions.ValidationError`, aliased at the import to distinguish
it from the DRF `serializers.ValidationError` raised two statements earlier in the same
method. If you add a validator check anywhere else, check the exception type against the
installed Django version rather than by name.

### 3. The forced-change rule made its own endpoint unreachable

`CsrfView` is `AllowAny`, but `AllowAny` controls _permissions_, not _authentication_. The
session authenticator still ran, so a user flagged `is_temporary_password` was answered
`403 password_change_required` when fetching a CSRF token - and without a token they could
not POST to `/auth/change-password/`, the very call the refusal was telling them to make.

What it looked like from outside: a user on a temporary password could never complete the
change. The screen said "you must change your password", the button returned 403, and no
combination of client behaviour got past it. **The rule was not too strict, it was
unusable.**

`CsrfView` is now in `ALLOWED_WHILE_PASSWORD_CHANGE_PENDING`, with a comment saying why.
`backend/tests/api/test_session_rules.py` asserts the allow list is exactly four
views, so removing it to "tighten" the list fails a test rather than shipping a dead end.

The general lesson: an allow list built from view classes needs every endpoint in the
_user's path through the flow_, not just the endpoint being protected. `me` (to render the
screen), `csrf` (to POST it), `change-password` (to satisfy it), `logout` (to escape it).

### Also worth knowing

- **`update_session_auth_hash()` does not rotate the CSRF token.** It cycles the _session
  key_, keeping the session valid. The `csrftoken` cookie is untouched and the token the
  client already holds stays valid. The OpenAPI description claimed otherwise and was
  corrected.
- **There is no per-session copy of "this user must change their password."** An earlier
  draft stamped it into the session at sign-in, on the reasoning that an administrative
  reset would not otherwise take effect. That was backwards: DRF reloads the user from the
  database on every request, so `is_temporary_password` is already current. The stamp only
  created a second source of truth that a reset could _not_ clear, keeping a restored
  account blocked until its session expired. One source of truth, read fresh.
- **Remote CI was never verified for this work** - no `gh`, no token, and the repository is
  private. The evidence is local only: 508 tests, ruff, ruff-format, `mypy .` over
  135 files, `manage.py check`, and no missing migrations.
- **`mypy .` is the gate, not `mypy apps config`.** The latter skips `tests/`, which is
  where the type errors worth catching in a security suite actually live. The roadmap's
  verification section said `apps config`; CI says `.`. The roadmap was wrong and now
  matches CI.

## A8: the permission gate was a test stand-in

The A8 gate is "a Cashier cannot approve payroll". Before this phase that sentence was
true of a _test file_, not of the application: `tests/api/urls_for_tests.py` defined its
own `HasPermission` and `HasApprovePayrollPermission`, and its two assertions passed
happily because nothing in `apps/` ever consulted `ROLE_MATRIX` at request time. The
matrix was declared, the seed migration applied it, `RolePermissionBackend` served it
– and no shipped code asked. The probe was testing the probe.

### What shipped

`apps/accounts/permissions.py` now carries `HasRolePermission` and one subclass per
capability (`CanApprovePayrollRun`, `CanVoidSale`, `CanManageSettings`, ...), registered
in `PERMISSION_CLASSES`. The test URLconf imports `CanApprovePayrollRun` instead of
defining its own, so the same assertions now exercise shipped enforcement.

Each class is one line:

```python
def has_permission(self, request: Request, view: Any) -> bool:
    return bool(request.user.has_perm(self.required_permission))
```

It does not read `ROLE_MATRIX` at request time, and that is deliberate. The matrix is
applied to `auth_permission` rows by the seed migration; a request-time lookup of the
constant would be a _second_ source of truth which could disagree with the rows actually
granted, and the disagreement would surface as a 403 in production with nothing in the
codebase able to explain it. Going through `has_perm` means the answer is always the
matrix the Owner reviews.

### Three things that turned out to be unnecessary

Each was written, then deleted after checking how the surrounding layers actually
behave. Recorded because the instinct to add them is reasonable and the code would have
been dead:

- **A custom `message()` naming the missing permission.** DRF passes
  `getattr(permission, "message", None)` to `permission_denied` _without calling it_
  (`rest_framework/views.py`), and `apps/core/exceptions.py` maps every
  `PermissionDenied` to one fixed string regardless. Had anything used it, the response
  would have contained a bound-method repr. The fixed string is also the better answer:
  a refusal naming the permission hands a Cashier a map of the grants they lack.
- **An explicit `is_active` check.** `RolePermissionBackend` returns an empty set for an
  inactive user, and `BarketSessionAuthentication` refuses one as 401 before any
  permission class runs. Verified directly, including with a Django-native grant added.
  The third check could never change a verdict, and would have gone stale the moment
  either layer moved.
- **Tests for roleless users and deleted role rows.** `User.role` is non-nullable with
  `on_delete=PROTECT`, so the database refuses to store either state; a test would have
  had to mock the model into something the schema forbids.

### The Manager case

The gate is checked for BarMan, Cashier **and** Manager. Manager is the one that
matters: it holds `payroll.generate_run`, so it has legitimate payroll access, but
`payroll.approve_run` is withheld. That is the only place the matrix encodes separation
of duties rather than a capability gradient – whoever computes the payroll figure
must not sign it off. A test using only a Cashier would have passed even if that
separation had been quietly dropped, so the matrix entry and the class behaviour are
each pinned separately.

### Coverage

`test_permission_classes_agree_with_the_matrix` is the full cross-product: 4 roles x 27
permissions, asserting the class verdict equals the matrix grant for every pair. Plus
coverage tests in both directions – every catalogued permission has a class, and no
class requires an uncatalogued permission – so a capability added to the matrix and
shipped without a class fails the build instead of being silently unreachable.

## A9: the 401 gate was never tested, only assumed

The A9 gate is "401/403 on every protected route". Nothing tested it. The contract suite
does prove every endpoint _declares_ `IsAuthenticated` — but by design its rules are pure
attribute reads (`contract.py:11-15`), which is the right trade for a suite that must stay
fast. The cost: every 401 in the suite hard-coded one URL, so an endpoint added tomorrow
with no protection whatsoever would fail nothing at all.

`tests/api/test_access_sweep.py` closes that gap with real requests. It imports
`discover_endpoints` from the contract engine and derives the public routes from the
contract's own `EXEMPTIONS` table, so a new endpoint cannot become public by being added
to a second list here — it would have to be exempted _there_, with a reason, and that
exemption is reviewed.

### Two real defects the sweep surfaced

Both were found by sending real traffic, and neither was visible to an attribute check:

- **`/api/docs/` escapes the error envelope entirely.** `SpectacularSwaggerView` is a
  Django template view, so its 401 is a plain `text/html` "401 Unauthorized" page
  produced outside DRF. There is no `error.code` for a client to branch on, and asking
  for JSON returns 406. `/api/schema/` goes through the handler but renders the envelope
  as YAML unless asked for JSON. Both are correctly _protected_ — status and
  `WWW-Authenticate` hold — and both are now asserted on exactly that, with the reason
  recorded in `NON_JSON_REFUSALS` so a change to either view's rendering shows up as a
  visible diff rather than a silently dropped assertion.
- **The login route's throttle reads the database.** The public-route check reached
  `LoginView`'s throttle before its permission check and died in the cache. The test now
  carries `django_db`; without it the failure would have been a false one.

### Vacuity and mutation

Every parameterised test would pass having issued zero requests if discovery returned
nothing, so `TestTheSweepIsNotVacuous` pins the endpoint count, the presence of protected
routes, and an exact partition of public against protected. The classifier was checked by
mutation — injecting a waiver for `MeView` flips `_is_public` to `True` and removing it
flips back — so it is not a constant that would make the whole file green.

### The role dimension is wired, not asserted

No shipped view names a `HasRolePermission` yet; the payroll endpoints come later. That
emptiness is an explicit assertion with a message explaining what it means, rather than
a test that silently matches nothing. The Cashier reachability check signs in per
endpoint (reusing one client would let the first request invalidate the session for the
rest, and the failure would read like a permission bug) and excludes `LogoutView`, since
logging out is the refusal it is being asked about.

## A10: a duplicate sale is unrecoverable, so the retry had to be impossible

The A10 gate is "the same key twice creates one sale, not two". Two things stood in the way of
proving it, and one of them was worse than a missing feature.

**The roadmap said "on write endpoints". There are no write endpoints.** Phase A is auth, and A2–A4
exist precisely to stop the API being grown by inventing routes. So the guarantee is delivered where
it lives — the service layer, where the key arrives as a keyword argument. The same guarantee then
covers a management command or a scheduled job that never touches HTTP, and the endpoint that later
reads the header becomes a thin adapter rather than the place the logic is. `IDEMPOTENCY_HEADER`
is defined next to the mechanism so the two cannot drift.

**`next_sale_reference()` was already racy, and the unique constraint was hiding it.** The number
is derived from `COUNT()` of the day's sales, which is what makes the no-skipped-numbers promise
possible — and two concurrent sales both read "3 used" and both return `S-20260929-0004`. The
`unique` on `Sale.reference` then let exactly one commit and turned the other into an
`IntegrityError`: a 500 for a cashier who did nothing wrong, on a number burned by a sale that never
landed. The count is now taken under a transaction-scoped `pg_advisory_xact_lock`, so it is
trustworthy, with the constraint left in place as the final authority. No counter table: that would
need its row to exist before the first sale of the day, which is a race of its own in a second
place, and it would take the single source of truth away from the sales table.

### The fingerprint was where the real risk was

A claim row makes the _mechanism_ correct. What it cannot do is decide that two payloads are the
same request, and getting that wrong fails in one of two ways, both bad. Hash too loosely and a
retry is refused as a reused key — a cashier who pressed the button twice sees a 409 for a sale that
already exists. Hash too tightly and a genuinely different request is answered with the first sale —
the caller believes its second, different basket was recorded.

Two bugs here were found by writing the tests, not by reading the code:

- **The fingerprint hashed the resolved `sold_at`, not the caller's.** `moment = sold_at or
now_utc()` means an ordinary client that never sends `sold_at` got a fresh timestamp per attempt,
  so no two attempts could ever match. The double-click the mechanism exists to absorb would have
  come back as a key-reuse error — the mechanism present and useless. The gate test failed on this
  before it was fixed, which is the only reason it was caught.
- **Amounts were stringified before being hashed**, which quietly defeated the `Decimal`
  normalisation `canonical` exists to perform. `Decimal("2.00")` and `Decimal("2")` are the same
  quantity, but `"2.00" != "2"` as text. Handing the `Decimal` over to be normalised is the whole
  point of having it (§10.3).

`canonical` also had a third gap: its docstring promised that `1` and `1.0` hash alike and the code
did not do it, so `int`, `float` and `Decimal` now share one tag. `bool` is checked first, because
it is an `int` subclass and `True` must not hash as `1`. A float artefact like `0.1 + 0.2` stays
_visible_ rather than being rounded onto the value a human probably meant — silently guessing about
money is worse than showing the caller something odd.

### The concurrency tests are marked `transaction=True`, and are checked by mutation

Under the default `django_db` the test runs inside a transaction that is rolled back, so a worker
thread on its own connection would not see the fixtures at all — the threads would race over an
empty database and pass without anything having been allocated. `transaction=True` commits the
setup so the workers genuinely contend for the same rows.

Both concurrency tests were verified by mutation rather than by being green:

- Removing the advisory lock fails `test_concurrent_receipt_numbers_are_distinct_and_leave_no_gap`
  with `IntegrityError: duplicate key value violates unique constraint
"sales_sale_reference_key"` — the exact production symptom the docstring predicts.
- Making `claim_key` not write its claim fails the double-click test with two sales, pk 1 and pk 2,
  from one key.

A concurrency test that cannot fail is worth nothing, so both were made to fail on purpose before
being allowed to pass.

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

### Tests

The Playwright suite has two halves, and they are not interchangeable.

| Command                    | Needs                              | What it proves                                                                                                        |
| -------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `npm run test:e2e:stubbed` | Node only                          | The frontend handles states no real server will produce on demand: a dead backend, a 502, a forced password change.   |
| `npm run test:e2e:live`    | Python, the backend deps, Postgres | The frontend and backend actually agree: a real session, a real CSRF token, a real 403, real rows in a real database. |
| `npm run test:e2e`         | both of the above                  | What CI runs: the stubbed project, then the live one, as two separate invocations.                                    |

The stubbed half answers the question "does this screen behave?", and it cannot answer
"do these two halves still fit together?" — a stub is written from the author's idea of
the backend, so it keeps agreeing with a frontend that drifted. The live half is the one
that catches drift, and it is why the stubbed specs are kept alongside it rather than
replaced by it.

The live half starts its own Django on port 8010 — deliberately not 8000, because a
developer usually has a server running there against their working database — and points
it at a disposable `barket_e2e` database that it flushes and reseeds on every run.
Creating that database is the only manual step:

```bash
docker compose exec db createdb -U barkot barkot_e2e
```

It then connects with `E2E_DB_NAME`, `E2E_DB_USER`, `E2E_DB_PASSWORD`, `E2E_DB_HOST` and
`E2E_DB_PORT`. The defaults are user `barket` on `127.0.0.1:5433`, which is where the
compose database publishes, but **the password has no usable default**: it is whatever
`DJANGO_DB_PASSWORD` was when your database volume was first created, so set
`E2E_DB_PASSWORD` to match. A mismatch fails immediately and says so, rather than
half-way through a test run.

```bash
E2E_DB_PASSWORD='<the same one your backend uses>' npm run test:e2e:live
```

`seed_e2e --reset` refuses to flush any database whose name does not end in `_e2e`, so a
mistyped `E2E_DB_NAME` fails loudly instead of erasing anything real.

## Architecture at a glance

| Layer      | Stack                                                                          |
| ---------- | ------------------------------------------------------------------------------ |
| Frontend   | Next.js 16.x (App Router) + TypeScript 5.9 + React 19.3 + Tailwind CSS 4.x     |
| Backend    | Django 5.2.x LTS + Django REST Framework 3.18.x, modular monolith              |
| Database   | PostgreSQL 17.x, the single system of record                                   |
| Web server | Nginx (TLS termination, `/` to web, `/api/v1/` to API)                         |
| Runtime    | Docker Compose on one commercially permitted VPS                               |
| Async      | Redis/Valkey + Celery — optional, added only when a real async workload exists |

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
