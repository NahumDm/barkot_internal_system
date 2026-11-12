# Backup and Restore Operations

This runbook covers backing up and restoring the Barkot database.

## Prerequisites

- PostgreSQL client tools installed (pg_dump, psql, pg_isready)
- Access to the database server with appropriate credentials
- Sufficient disk space for backups

## Environment Variables

Set these to match your environment:

```bash
export PG_HOST=127.0.0.1
export PG_PORT=5432
export PG_USER=barkot
export PGPASSWORD=barkot
export DJANGO_DB_NAME=barkot
```

## Creating a Backup

Use the backup script from `infrastructure/scripts/backup.sh`:

```bash
cd infrastructure/scripts
./backup.sh [database_name] [backup_dir]
```

By default: backs up `barkot` to `/var/backups/barkot/` with timestamped filename `barkot_YYYYMMDD_HHMMSSZ.sql.gz`.

## Restoring from Backup

Use the restore script from `infrastructure/scripts/restore.sh`:

```bash
cd infrastructure/scripts
./restore.sh <backup_file> [target_db_name]
```

If `target_db_name` is provided, the script drops and recreates it. If omitted, it restores into the database named in the backup (requires `--clean --create` in backup).

**IMPORTANT:** Restoring to an existing database will destroy data. Always verify the target database name.

## Restore Drill (D3 Gate)

The D3 gate requires: "A restore drill: restore into a scratch database and reconcile"

To perform the drill:

1. Seed or ensure source database has known state (e.g., run `manage.py seed_e2e --reset` or create test data)
2. Create a backup of the source database
3. Create a scratch database (e.g., `barkot_restore_test_<timestamp>`)
4. Restore the backup into the scratch database
5. Reconcile: compare record counts and key aggregates between source and restored databases
6. Verify the application can connect to the restored database and core functionality works

## Automated Reconciliation Example

```bash
# Get counts from source
psql -h $PG_HOST -U $PG_USER -d $SOURCE_DB -c "
SELECT 'users' as table, count(*) FROM accounts_user
UNION ALL SELECT 'sales', count(*) FROM sales_sale
UNION ALL SELECT 'products', count(*) FROM products_product;
"

# Compare with restored
psql -h $PG_HOST -U $PG_USER -d $RESTORED_DB -c "
SELECT 'users' as table, count(*) FROM accounts_user
UNION ALL SELECT 'sales', count(*) FROM sales_sale
UNION ALL SELECT 'products', count(*) FROM products_product;
"
```

Keys to reconcile: total record counts by table, latest IDs, and checksums of critical business data.
