#!/bin/bash
# Automated restore drill - verifies backup/restore works correctly
# Creates backup, restores to scratch DB, reconciles data
set -euo pipefail

PG_HOST="${PG_HOST:-127.0.0.1}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-barkot}"
PGPASSWORD="${PGPASSWORD:-barkot}"
SOURCE_DB="${SOURCE_DB:-barkot}"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
SCRATCH_DB="${SCRATCH_DB:-barkot_restore_drill_${TIMESTAMP}}"
BACKUP_DIR="${BACKUP_DIR:-/tmp/barkot_backups}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "${BACKUP_DIR}"

echo "=== Restore Drill Starting ==="
echo "Source: ${SOURCE_DB}"
echo "Scratch: ${SCRATCH_DB}"
echo "Backup dir: ${BACKUP_DIR}"

# Create backup
echo "--- Creating backup ---"
BACKUP_FILE=$("${SCRIPT_DIR}/backup.sh" "${SOURCE_DB}" "${BACKUP_DIR}" | tail -1)
echo "Backup: ${BACKUP_FILE}"

# Restore to scratch DB
echo "--- Restoring to scratch DB ---"
"${SCRIPT_DIR}/restore.sh" "${BACKUP_FILE}" "${SCRATCH_DB}"

# Reconcile
echo "--- Reconciling ---"
# Function to get table counts
get_counts() {
  local db=$1
  PGPASSWORD="${PGPASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${db}" -t -c "
    SELECT schemaname, relname, n_live_tup 
    FROM pg_stat_user_tables 
    ORDER BY schemaname, relname;
  " 2>/dev/null || true
}

echo "Source counts:"
get_counts "${SOURCE_DB}"

echo -e "\nScratch counts:"
get_counts "${SCRATCH_DB}"

# Compare counts (simplified reconciliation)
DIFF=$(PGPASSWORD="${PGPASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d postgres -t -c "
  SELECT COUNT(*) FROM (
    SELECT s.schemaname, s.relname, s.n_live_tup as s_count, r.n_live_tup as r_count
    FROM pg_stat_user_tables s
    LEFT JOIN dblink('dbname=${SCRATCH_DB} host=${PG_HOST} port=${PG_PORT} user=${PG_USER} password=${PGPASSWORD}',
      'SELECT schemaname, relname, n_live_tup FROM pg_stat_user_tables') 
      AS r(schemaname text, relname text, n_live_tup bigint)
      ON s.schemaname=r.schemaname AND s.relname=r.relname
    WHERE s.n_live_tup != r.n_live_tup OR r.n_live_tup IS NULL
  ) t;
" 2>&1 | tr -d '[:space:]')

if [ "${DIFF}" = "0" ]; then
  echo -e "\n✓ Reconciliation PASSED: All table row counts match"
  # Cleanup
  PGPASSWORD="${PGPASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${SCRATCH_DB};" >/dev/null 2>&1
  echo "Cleaned up scratch DB: ${SCRATCH_DB}"
  exit 0
else
  echo -e "\n✗ Reconciliation FAILED: ${DIFF} table(s) have mismatched counts"
  # Don't cleanup on failure for debugging
  echo "Scratch DB preserved for inspection: ${SCRATCH_DB}"
  exit 1
fi
