## Deployment Rehearsal (D6)

**Gate**: Full stack starts from `docker compose.prod.yml` with real secrets. Verify on a target host/staging environment.

### Pre-requisites
- Target host running Ubuntu 24.04 LTS with Docker + Docker Compose
- Domain DNS pointing to host (or test domain)
- Nginx installed on host
- Real secrets (not dev defaults) prepared securely
- Valid TLS certificates (Let’s Encrypt or provided)

### Rehearsal Steps

1. **Prepare secrets**
   - Create `.env` with production values
   - Generate strong `DJANGO_SECRET_KEY` (>=50 chars)
   - Set all required DB/host/security vars
   - Verify no secrets in git

2. **Deploy from scratch**
   ```bash
   git clone https://github.com/NahumDm/barkot_internal_system.git
   cd barkot_internal_system
   # Configure .env
   docker compose --env-file .env -f docker-compose.prod.yml up -d --build
   docker compose --env-file .env -f docker-compose.prod.yml exec api python manage.py migrate --no-input
   docker compose --env-file .env -f docker-compose.prod.yml exec api python manage.py create_owner owner
   ```

   Roles are seeded by `post_migrate`; only the Owner account is created
   explicitly. There is **no `collectstatic` step**: `django.contrib.staticfiles`
   is not installed, the API serves no static assets, and the frontend is a
   separate Next.js container.

3. **Configure host nginx**
   ```bash
   sudo cp infrastructure/nginx/nginx.conf /etc/nginx/nginx.conf
   sudo cp infrastructure/nginx/conf.d/barkot.conf /etc/nginx/conf.d/barkot.conf
   sudo nginx -t && sudo systemctl reload nginx
   ```

4. **Verify full stack**
   - [ ] All containers healthy (`docker compose ps`)
   - [ ] Health endpoints: `/health/live` and `/health/ready` return 200
   - [ ] Frontend accessible via HTTPS
   - [ ] API accessible under `/api/v1/`
   - [ ] Login works with seeded/real users
   - [ ] Core flows (sales, inventory, payroll, reports) functional
   - [ ] Request IDs in logs/headers
   - [ ] Backup/restore scripts work against real DB

5. **Rollback test** (as per production runbook)
   - [ ] Rollback to previous image works
   - [ ] Database restore from backup works (restore drill executed)

6. **Smoke tests**
   ```bash
   curl -I https://your-domain.com/health/live
   curl -I https://your-domain.com/health/ready
   ```

### Acceptance Criteria
- Stack starts cleanly from scratch using only `docker-compose.prod.yml` and scripts
- No dev defaults used in production
- All health checks green
- TLS/HTTPS working correctly
- Rollback procedure validated

## Rehearsal log

### 2026-10-08 — Local rehearsal (Docker Desktop on Windows)

Stack built and started from `docker-compose.prod.yml` with generated secrets
(50+ char `DJANGO_SECRET_KEY`, random DB password), on a scratch DB
(`barkot_prod`).

- `docker compose -f docker-compose.prod.yml up -d --build` — db/api/web all Up,
  db healthy.
- `manage.py migrate --no-input` — all migrations applied.
- `curl http://127.0.0.1:8000/health/live` and `/health/ready` — 200/200.
- Web `http://127.0.0.1:3000/` — 307 to `/dashboard`; `/login` — 200.
- `GET /api/v1/` — 200.
- `seed_e2e` ran in the scratch DB; owner login via
  `POST /api/v1/auth/login/` (CSRF cookie + `X-CSRFToken`) — 200, role OWNER.
- Authenticated `GET /api/v1/dashboard/` — 200, `X-Request-ID` response header
  present (D5).
- nginx `nginx -t` validated in `nginx:alpine` against the repo config with a
  scratch self-signed certificate — syntax OK, test successful; only warning is
  the `listen ... http2` deprecation on nginx >= 1.25 (`Ubuntu 24.04 ships
  1.24`, where the current form is correct).
- `zone=login` (10r/m) is now wired onto `location /api/v1/auth/login/`,
  exploding the old unused-zone gap from the handoff.
- Full teardown: `docker compose down -v`, scratch `.env` deleted (it is
  gitignored and regenerated per rehearsal).

Deviations (documented, not a bug): `DJANGO_SECURE_SSL_REDIRECT` and the secure
cookie flags were set false because there is no TLS termination on a local
rehearsal; the target host keeps them true behind nginx.
**Blocked on the client decision:** a milestone rehearsal against a real Ubuntu
24.04 VPS with a domain and Let's Encrypt certs (open question 9/10 in
`docs/business/client-decisions.md`).
