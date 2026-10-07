-- One `docker compose up -d` should be the whole environment, and the live
-- Playwright specs (frontend/tests/live) need a disposable database to happen
-- against. Docker's entrypoint runs everything in this directory once, on the
-- first boot of a fresh `db_data` volume, so a fresh clone gets `barkot_e2e`
-- without anyone creating it by hand and without hunting for psql.
--
-- The name must stay in step with the `E2E_DB_NAME` default in
-- frontend/tests/live/environment.ts. Both are set in their own home; this
-- comment is the handshake that keeps them the same.
--
-- `\gexec` makes the statement idempotent, so re-running this file against a
-- database that already has the e2e schema is harmless.
SELECT 'CREATE DATABASE barkot_e2e'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'barkot_e2e')\gexec