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
   docker compose --env-file .env -f docker-compose.prod.yml exec api python manage.py collectstatic --no-input
   ```

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
