# Production Runbook

This runbook provides step-by-step instructions for deploying, operating, and rolling back Barkot. It is written so a second person can deploy and roll back from this document alone (D4 gate).

## Prerequisites

- Ubuntu 24.04 LTS VPS with Docker and Docker Compose installed
- Domain name pointing to the VPS (e.g., barkotbar.com)
- Nginx installed on the host (for TLS termination as specified in topology)
- PostgreSQL client tools for diagnostics (optional)
- Required secrets configured in `.env` file
- SSH access to the VPS with sudo privileges

## Architecture Overview

Single VPS topology:
- Nginx on the host terminates TLS and proxies traffic
- Docker Compose runs: `db` (PostgreSQL 17), `api` (Django/Gunicorn), `web` (Next.js)
- Services only publish on `127.0.0.1` to the host; PostgreSQL not exposed publicly
- Nginx routes `/api/v1/` to API, everything else to web; `/health/` to API health check

See `infrastructure/nginx/` and `docker-compose.prod.yml` for full configuration.

## Initial Deployment

### 1. Prepare Environment

Create `.env` file in repository root on VPS. Required variables:
```bash
DJANGO_SECRET_KEY=<strong-random-secret>
DJANGO_ALLOWED_HOSTS=barkotbar.com,www.barkotbar.com,127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://barkotbar.com,https://www.barkotbar.com,http://127.0.0.1:3000
DJANGO_DB_NAME=barkot
DJANGO_DB_USER=barkot
DJANGO_DB_PASSWORD=<strong-db-password>
DJANGO_TRUSTED_PROXY=true
DJANGO_SESSION_COOKIE_SECURE=true
DJANGO_CSRF_COOKIE_SECURE=true
DJANGO_SECURE_SSL_REDIRECT=true
BUSINESS_CURRENCY=ETB
BUSINESS_TIMEZONE=Africa/Addis_Ababa
NEXT_PUBLIC_APP_NAME=Barkot
```

### 2. Configure Nginx on Host

Copy nginx configs:
```bash
sudo cp infrastructure/nginx/nginx.conf /etc/nginx/nginx.conf
sudo cp infrastructure/nginx/conf.d/barkot.conf /etc/nginx/conf.d/barkot.conf
sudo nginx -t
sudo systemctl reload nginx
```

### 3. Deploy with Docker Compose

```bash
# Pull/build and start services
docker compose --env-file .env -f docker-compose.prod.yml up -d --build

# Verify services are healthy
docker compose --env-file .env -f docker-compose.prod.yml ps
docker compose --env-file .env -f docker-compose.prod.yml logs api
docker compose --env-file .env -f docker-compose.prod.yml logs web
```

### 4. Run Database Migrations

```bash
docker compose --env-file .env -f docker-compose.prod.yml exec api python manage.py migrate --no-input
```

### 5. Seed Data (if needed)

```bash
docker compose --env-file .env -f docker-compose.prod.yml exec api python manage.py seed --no-input
# Or for E2E testing environment only: python manage.py seed_e2e --reset
```

### 6. Verify Deployment

- Check health endpoint: `curl -i https://barkotbar.com/health/`
- Check API: `curl -i https://barkotbar.com/api/v1/`
- Check frontend: browse to `https://barkotbar.com`

## Operational Procedures

### Service Management

```bash
# Start all services
docker compose --env-file .env -f docker-compose.prod.yml up -d

# Stop all services
docker compose --env-file .env -f docker-compose.prod.yml down

# Restart specific service
docker compose --env-file .env -f docker-compose.prod.yml restart api

# View logs
docker compose --env-file .env -f docker-compose.prod.yml logs -f api
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=50 web
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=50 db
```

### Database Operations

#### Backup (see backup-restore.md for details)
```bash
# Create backup
cd infrastructure/scripts
PGHOST=127.0.0.1 PGPORT=5432 PGUSER=$DJANGO_DB_USER PGPASSWORD=$DJANGO_DB_PASSWORD \
  ./backup.sh $DJANGO_DB_NAME /var/backups/barkot
```

#### Restore from backup (emergency only)
```bash
# Restore to target DB - DESTROYS existing data
cd infrastructure/scripts
PGHOST=127.0.0.1 PGPORT=5432 PGUSER=$DJANGO_DB_USER PGPASSWORD=$DJANGO_DB_PASSWORD \
  ./restore.sh /var/backups/barkot/<backup-file>.sql.gz <target-db>
```

#### Restore Drill (D3 gate)
```bash
cd infrastructure/scripts
PGHOST=127.0.0.1 PGPORT=5432 PGUSER=$DJANGO_DB_USER PGPASSWORD=$DJANGO_DB_PASSWORD \
  SOURCE_DB=$DJANGO_DB_NAME ./restore-drill.sh
```

### Security & Monitoring

- Rotate secrets (DJANGO_SECRET_KEY, DB passwords) regularly; after rotation, restart all services
- Monitor disk space for DB volume (`db_data`) and backup storage
- Monitor logs for 5xx errors (see D5 observability baseline when implemented)
- Keep images up to date: rebuild with `docker compose --env-file .env -f docker-compose.prod.yml up -d --build`
- Nginx access/error logs: `/var/log/nginx/`

## Rollback Procedure

A second person can perform rollback by following these steps. Rollback is to the previously known-good image/tag and database backup.

### Option 1: Rollback to previous Docker images (code rollback)

If you need to rollback application code without touching DB:
```bash
# Tag current as backup (if desired)
docker image ls

# Revert to previous commit/tag and rebuild
git log --oneline -5
git checkout <previous-commit-or-tag>
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
docker compose --env-file .env -f docker-compose.prod.yml exec api python manage.py migrate --no-input
```

### Option 2: Full rollback including database (disaster recovery)

Only do this if data corruption occurred. Requires recent backup.

1. **Stop services**:
```bash
docker compose --env-file .env -f docker-compose.prod.yml down
```

2. **Restore database from known-good backup**:
```bash
cd infrastructure/scripts
PGHOST=127.0.0.1 PGPORT=5432 PGUSER=$DJANGO_DB_USER PGPASSWORD=$DJANGO_DB_PASSWORD \
  ./restore.sh /var/backups/barkot/<known-good-backup>.sql.gz $DJANGO_DB_NAME
```

3. **Deploy known-good code**:
```bash
git checkout <known-good-commit-or-tag>
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
docker compose --env-file .env -f docker-compose.prod.yml exec api python manage.py migrate --no-input
```

4. **Verify**:
- Health check passes
- Critical flows work (login, sales, inventory, payroll, reports)
- Nginx routing correct

## Troubleshooting

### Services won't start
- Check `.env` has all required vars
- Check disk space: `df -h`
- Check Docker: `docker system df`
- View logs: `docker compose logs <service>`

### DB connection issues
- Verify DB container healthy: `docker compose ps`
- Check pg_isready: `docker exec barkot-prod-db-1 pg_isready -U $USER`
- Confirm network connectivity between api and db

### Nginx issues
- Test config: `sudo nginx -t`
- Check error logs: `sudo tail -f /var/log/nginx/error.log`
- Verify SSL certs valid

### API returning 500s
- Check API logs: `docker compose logs -f api`
- Check Django settings are correct for prod (DEBUG=False, allowed hosts, secure cookies)
- Run migrations: `docker compose exec api python manage.py migrate --check`

## Observability (D5)

- Request ID: All requests get `X-Request-ID` header (from nginx or generated). Logs include `request_id` and `user_id`.
- Health endpoints: `GET /health/live` and `GET /health/ready` — monitor for 503s and timeouts.
- Alerting recommendations:
  - Alert on 5xx responses (rate > threshold over time window)
  - Alert on `/health/ready` returning 503 (DB connectivity issues)
  - Alert on `/health/live` failing (process down)

## Health Checks

- API health: `GET /health/` should return 200
- Database: `pg_isready` on db container
- All containers: `docker compose ps` shows "healthy"/"Up"

## Rollback Verification Checklist

After rollback, verify:
- [ ] All services running and healthy
- [ ] Frontend loads at https://barkotbar.com
- [ ] API responds at https://barkotbar.com/api/v1/
- [ ] Login works for seeded users
- [ ] Core business flows functional (sales, inventory, payroll, reports)
- [ ] Database state matches expected (check key counts)
- [ ] No unexpected errors in logs
