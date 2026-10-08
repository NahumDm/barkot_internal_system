/**
 * The real backend the live Playwright specs run against (roadmap B5).
 *
 * Everything here exists to make one thing possible and unambiguous: a browser
 * that talks to an actual Django, which talks to an actual Postgres. The stubbed
 * specs in `tests/e2e/session.ts` answer `/auth/me/` at the network layer and are
 * kept - they cover states a real backend cannot be asked to produce on demand,
 * like a 502 or a temporary password. But a stub proves the frontend behaves as
 * its author imagined the backend would, and that is how a category route that
 * resolved to a product retrieve shipped green. The specs in `tests/live/` cross
 * the real seam instead.
 *
 * Three choices make that safe and repeatable.
 *
 * **Its own port.** 8010, not 8000. A developer very often has `runserver` on
 * 8000 pointed at their working database, and Playwright reuses an existing
 * server outside CI. Reusing that would sell barkot's real books during a test
 * run. A port nobody else uses means the E2E can only ever be talking to the
 * process this configuration started.
 *
 * **Its own database.** `barkot_e2e`, never the development one, and the seed
 * command refuses to erase anything whose name does not end in `_e2e`.
 *
 * **One origin.** The browser stays on 127.0.0.1:3000 and Next forwards
 * `/api/v1/` to Django server-side, which is why the session and CSRF cookies
 * behave the way they do in production and why no CORS configuration is needed.
 */

import fs from "node:fs";
import path from "node:path";

/** Port for the Django process Playwright starts. Deliberately not 8000. */
export const E2E_API_PORT = 8010;

/** Where that Django listens. Server-side only; the browser never learns it. */
export const API_ORIGIN = `http://127.0.0.1:${E2E_API_PORT}`;

/**
 * Readiness probe. `/health/ready` checks the database, so this only answers 200
 * once `migrate` has actually finished - the alternative, `/health/live`, would
 * let Playwright start testing against a schema that does not exist yet.
 */
export const API_READY_URL = `${API_ORIGIN}/health/ready`;

/** The browser's origin. Matches the `baseURL` the specs navigate against. */
export const FRONTEND_ORIGIN = "http://127.0.0.1:3000";

/**
 * Readiness probe for the Next server, and deliberately a page rather than the
 * bare origin.
 *
 * Waiting on `/` proves only that the port is open: `/` is prerendered at build
 * time, so it answers even when the app cannot render a real route. Waiting on
 * `/login` asserts the thing the live specs actually need - that the server can
 * serve a page - and has the useful side effect of warming that route, which is
 * why the first sign-in assertion is not the one that pays for a cold production
 * build. It was, and it failed intermittently with the alert never appearing.
 */
export const FRONTEND_READY_URL = `${FRONTEND_ORIGIN}/login`;

/**
 * Database name; the `_e2e` suffix is what `seed_e2e --reset` insists on.
 *
 * Same naming as the rest of the stack: the development database and role come
 * from `docker-compose.yml` (`barkot`/`barkot`), so the disposable one is
 * `barkot_e2e` rather than paying for an extra role to rename.
 */
export const E2E_DB_NAME = "barkot_e2e";

/**
 * The frontend checkout.
 *
 * Found by looking for `playwright.config.ts` rather than by assuming the working
 * directory, because this module is loaded from the config, from global setup and
 * from inside test workers, and assuming would mean three chances to be wrong.
 * Both this and the backend directory can be overridden for unusual layouts.
 */
export const FRONTEND_DIR = resolveFrontendDir();

/** The backend checkout, always the sibling of the frontend one. */
export const BACKEND_DIR =
  process.env.E2E_BACKEND_DIR ?? path.resolve(FRONTEND_DIR, "..", "backend");

/**
 * Where `seed_e2e --json` output is left for the specs to read.
 *
 * A file rather than an environment variable because Playwright workers are
 * already running by the time a variable set in global setup could be relied on,
 * and a file written before the first test starts cannot be missed. Gitignored,
 * because it is generated state rather than source.
 */
export const SEED_FILE = path.resolve(FRONTEND_DIR, "tests", "live", ".seeded.json");

/** One seeded user, as `seed_e2e` created them. */
export interface SeededUser {
  username: string;
  password: string;
}

/** The seeded product the live specs sell. */
export interface SeededProduct {
  id: number;
  name: string;
  sku: string;
  unit_price: string;
  opening_stock: string;
}

/** Everything the specs need to know about the seeded database. */
export interface SeedSummary {
  database: string;
  cashier: SeededUser;
  manager: SeededUser;
  owner: SeededUser;
  barman: SeededUser;
  category: { id: number; name: string };
  product: SeededProduct;
  /** The one staff member the payroll specs generate a run for. */
  payroll: {
    profile_id: number;
    employee_id: number;
    full_name: string;
    monthly_wage: string;
  };
}

/** Read what global setup seeded. Fails loudly rather than returning defaults. */
export function readSeedSummary(): SeedSummary {
  if (!fs.existsSync(SEED_FILE)) {
    throw new Error(
      `Seeded fixtures are missing at ${SEED_FILE}. The live specs need the ` +
        `global setup in tests/live/global-setup.ts to have run first.`,
    );
  }
  return JSON.parse(fs.readFileSync(SEED_FILE, "utf8")) as SeedSummary;
}

/**
 * The Python that runs Django: the project's own virtualenv on Windows, whatever
 * is on PATH elsewhere. CI has no venv and relies on the latter.
 */
export function pythonExecutable(): string {
  const configured = process.env.E2E_PYTHON;
  if (configured) return configured;
  if (process.platform === "win32") {
    return path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe");
  }
  return "python";
}

/**
 * Environment for every Django process this suite starts - the server and the
 * management commands alike, so the seed writes to the same database the specs
 * read from. Connection details are overridable because a developer's Postgres
 * is somewhere other than CI's, and the fallbacks mirror the defaults in
 * `docker-compose.yml` so the suite works out of the box.
 */
export function djangoEnv(): NodeJS.ProcessEnv {
  return {
    ...process.env,
    DJANGO_SETTINGS_MODULE: "config.settings.dev",
    DJANGO_DB_NAME: process.env.E2E_DB_NAME ?? E2E_DB_NAME,
    DJANGO_DB_USER: process.env.E2E_DB_USER ?? "barkot",
    DJANGO_DB_PASSWORD: process.env.E2E_DB_PASSWORD ?? "barkot",
    DJANGO_DB_HOST: process.env.E2E_DB_HOST ?? "127.0.0.1",
    DJANGO_DB_PORT: process.env.E2E_DB_PORT ?? "5433",
    DJANGO_ALLOWED_HOSTS: "127.0.0.1,localhost",
    // The browser's origin. Django compares this against the request when it
    // validates the CSRF token, and behind Next's proxy the browser never
    // appears to be talking to :8010 at all.
    DJANGO_CSRF_TRUSTED_ORIGINS: `${FRONTEND_ORIGIN},http://localhost:3000`,
  };
}

/**
 * The same environment, narrowed to what Playwright's `webServer.env` accepts.
 *
 * `ProcessEnv` admits `undefined` values and Playwright's does not; the only
 * entries that can be undefined are inherited ones, which are already strings
 * whenever they exist.
 */
export function djangoEnvForServer(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(djangoEnv())) {
    if (value !== undefined) env[key] = value;
  }
  return env;
}

/**
 * Whether the live project is part of this run.
 *
 * With no `--project` filter the whole suite runs and the answer is yes. With a
 * filter, the live project has to be one of the names. Reading the flag is blunt,
 * but it is the only selection signal available before Playwright resolves its
 * projects, and the consequence of getting it wrong is asymmetric: starting a
 * Django that nothing talks to, or seeding a database nothing reads, only costs
 * time, whereas skipping when it was needed fails loudly on the missing server or
 * the missing fixtures file.
 *
 * Lives here rather than in either caller because two callers need it and they
 * must agree: if the config started Django for a run the global setup declined to
 * seed, the live specs would find a live server with nothing in it.
 */
export function liveProjectSelected(argv: string[] = process.argv): boolean {
  const inline = argv.find((arg) => arg.startsWith("--project="));
  if (inline) return inline.slice("--project=".length).split(",").includes("live");
  const separator = argv.findIndex((arg) => arg === "--project" || arg === "-p");
  if (separator === -1) return true;
  return (argv[separator + 1] ?? "").split(",").includes("live");
}

function resolveFrontendDir(): string {
  const configured = process.env.E2E_FRONTEND_DIR;
  if (configured) return configured;
  const candidates = [process.cwd(), path.resolve(process.cwd(), "..", "frontend")];
  const found = candidates.find((dir) => fs.existsSync(path.join(dir, "playwright.config.ts")));
  if (found) return found;
  throw new Error(
    "Could not locate the frontend directory (no playwright.config.ts in the working " +
      "directory or its parent). Run the suite from the frontend directory, or point " +
      "E2E_FRONTEND_DIR at the checkout.",
  );
}
