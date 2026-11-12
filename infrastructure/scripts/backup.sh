#!/bin/bash
# Backup PostgreSQL database
# Usage: ./backup.sh [database_name] [backup_dir]
set -euo pipefail

DB_NAME="${1:-${DJANGO_DB_NAME:-barkot}}"
BACKUP_DIR="${2:-/var/backups/barkot}"
PG_HOST="${PG_HOST:-127.0.0.1}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-${DJANGO_DB_USER:-barkot}}"

mkdir -p "${BACKUP_DIR}"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

PGPASSWORD="${PG_PASSWORD:-${DJANGO_DB_PASSWORD:-}}" pg_dump \
  -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" \
  --clean --if-exists --create \
  "${DB_NAME}" | gzip > "${BACKUP_FILE}"

echo "Backup created: ${BACKUP_FILE}"
echo "${BACKUP_FILE}"
