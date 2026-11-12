#!/bin/bash
# Restore PostgreSQL database from backup
# Usage: ./restore.sh <backup_file> [target_db_name]
set -euo pipefail

BACKUP_FILE="${1:-}"
TARGET_DB="${2:-}"

if [ -z "${BACKUP_FILE}" ]; then
  echo "Usage: $0 <backup_file> [target_db_name]" >&2
  exit 1
fi

PG_HOST="${PG_HOST:-127.0.0.1}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-${DJANGO_DB_USER:-barkot}}"
PGPASSWORD="${PG_PASSWORD:-${DJANGO_DB_PASSWORD:-}}"

# If backup is gzipped, decompress
if [[ "${BACKUP_FILE}" == *.gz ]]; then
  TMP_SQL=$(mktemp /tmp/barkot_restore_XXXXXX.sql)
  trap 'rm -f ${TMP_SQL}' EXIT
  gunzip -c "${BACKUP_FILE}" > "${TMP_SQL}"
  SQL_FILE="${TMP_SQL}"
else
  SQL_FILE="${BACKUP_FILE}"
fi

if [ -n "${TARGET_DB}" ]; then
  # Create/replace target DB - requires --clean --create in backup or we handle separately
  PGPASSWORD="${PGPASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${TARGET_DB};"
  PGPASSWORD="${PGPASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d postgres -c "CREATE DATABASE ${TARGET_DB};"
  PGPASSWORD="${PGPASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${TARGET_DB}" < "${SQL_FILE}"
  echo "Restored to ${TARGET_DB} from ${BACKUP_FILE}"
else
  PGPASSWORD="${PGPASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d postgres < "${SQL_FILE}"
  echo "Restored from ${BACKUP_FILE}"
fi
