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
| Tests | 315 passing – domain invariants, permission matrix, production config guards, error envelope, API base, pagination, endpoint contract rules, `create_owner` bootstrap, session auth endpoints, login rate limiting, session timeout and forced password change |
| Static analysis | mypy clean (113 files), ruff clean |
| Authentication | Custom user, 4-role permission matrix, session/CSRF settings wired. `manage.py create_owner` creates the first Owner. Session auth is live: `/auth/csrf`, `/auth/login`, `/auth/logout`, `/auth/me`, `/auth/change-password`. Login is rate limited to 5 attempts a minute per client address, counted in the database so the budget is shared between Gunicorn workers. Sessions idle out after a configurable timeout (default 8 hours, Owner setting) and are answered `403 session_expired`. An account flagged `is_temporary_password` can reach only `/auth/me`, `/auth/logout`, `/auth/csrf` and `/auth/change-password` until it sets a new one; everything else answers `403 password_change_required`. |
| **API** | **Versioned under `/api/v1/`, one error envelope for every failure, pagination with a hard cap, the five session auth endpoints, rate limiting on login, and an OpenAPI schema that documents every one of them with its security scheme. No business endpoints yet.** |
| **Frontend** | **Shell only. 24 files, no API client, no auth, 7 feature directories empty.** |
| `reports` app | `apps.py` only |
| Audit | `AuditLog.record()` called from services; no API to read it |
| **Contract suite** | **`tests/api/contract.py` — 5 rules every registered endpoint must satisfy, with declared exemptions. A new endpoint is checked automatically.** |
| **Owner bootstrap** | **`manage.py create_owner <username>` — the password is read from a no-echo prompt or stdin, never an argument. `--generate-password` prints once; `--check` is a bare preflight.** |
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
`except` clause named the non-existent attribute, so it raised `AttributeError` *while
handling a rejection*.

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

`CsrfView` is `AllowAny`, but `AllowAny` controls *permissions*, not *authentication*. The
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
*user's path through the flow*, not just the endpoint being protected. `me` (to render the
screen), `csrf` (to POST it), `change-password` (to satisfy it), `logout` (to escape it).

### Also worth knowing

- **`update_session_auth_hash()` does not rotate the CSRF token.** It cycles the *session
  key*, keeping the session valid. The `csrftoken` cookie is untouched and the token the
  client already holds stays valid. The OpenAPI description claimed otherwise and was
  corrected.
- **There is no per-session copy of "this user must change their password."** An earlier
  draft stamped it into the session at sign-in, on the reasoning that an administrative
  reset would not otherwise take effect. That was backwards: DRF reloads the user from the
  database on every request, so `is_temporary_password` is already current. The stamp only
  created a second source of truth that a reset could *not* clear, keeping a restored
  account blocked until its session expired. One source of truth, read fresh.
- **Remote CI was never verified for this work** - no `gh`, no token, and the repository is
  private. The evidence is local only: 315 tests, ruff, ruff-format, mypy over 113 files,
  `manage.py check`, and no missing migrations.

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
