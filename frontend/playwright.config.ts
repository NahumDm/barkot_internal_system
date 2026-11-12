import { defineConfig, devices } from "@playwright/test";

import {
  API_ORIGIN,
  API_READY_URL,
  BACKEND_DIR,
  djangoEnvForServer,
  FRONTEND_ORIGIN,
  FRONTEND_READY_URL,
  liveProjectSelected,
  pythonExecutable,
  E2E_API_PORT,
} from "./tests/live/environment";

/**
 * Two ways to run the same suite (roadmap B5).
 *
 * `chromium` is the original: `next start` on its own, with the API answered by
 * network stubs. It is fast, needs nothing but Node, and is the only way to
 * reproduce a backend that is unreachable or a user on a temporary password -
 * states no real server can be asked to produce on demand. Those specs stay.
 *
 * `live` is the one that closes the gap. It talks to a Django that Playwright
 * starts here, pointed at a disposable database, with Next forwarding `/api/v1/`
 * to it so the browser keeps a single origin. A cashier's session, a CSRF token,
 * a role refusal and a Postgres row are all real.
 *
 * The two share one Next server when both run in a single invocation, which is
 * safe because stubs are installed per page: the stubbed specs intercept their own
 * requests and never reach Django, while the live specs install no routes at all
 * and therefore always do.
 *
 * Django itself is conditional, and `npm run test:e2e` runs the projects as two
 * separate invocations rather than one. That is deliberate. `page.route` only
 * intercepts the browser's requests, so an `(app)` page's server-side render still
 * asks the real origin for `/auth/me/`; with Django up, every stubbed navigation
 * pays a database round trip, and four workers doing that at once pushed redirect
 * assertions past their timeout. Splitting the invocations keeps the stubbed project
 * fast and honest about having no backend, gives CI two separately attributable
 * results, and costs one extra production build. `--project=chromium` runs with no
 * Postgres and no Python at all, which is the point of having it: working on the
 * frontend should not require a database. See `liveProjectSelected` for how the
 * selection is read.
 */

/** Quote the interpreter: a Windows checkout path can contain spaces. */
const python = `"${pythonExecutable()}"`;

const nextServer = {
  command: "npm run build && npm run start",
  url: FRONTEND_READY_URL,
  env: {
    // A production build, so the dev proxy is off unless asked for. The live
    // project is the ask: Next forwards /api/v1/ to the Django above, keeping
    // the browser on one origin exactly as Nginx does in production. The
    // stubbed project has no Django, so proxying there would only turn every
    // intentionally un-stubbed call into a connection-refused log and a
    // hanging browser resource; a fast 404 is the honest answer.
    API_PROXY_ENABLED: liveProjectSelected() ? "1" : "0",
    API_PROXY_TARGET: API_ORIGIN,
  },
  reuseExistingServer: !process.env.CI,
  // Generous, because this one is `next build && next start` and a cold
  // production build is the slowest thing in the suite by a wide margin.
  timeout: 300_000,
};

const djangoServer = {
  // Migrate first, then serve. Playwright waits for /health/ready, which
  // checks the database, so a test can never start against a schema that is
  // not there yet even though the process is listening.
  command:
    `${python} manage.py migrate --no-input && ` +
    `${python} manage.py runserver 127.0.0.1:${E2E_API_PORT} --noreload`,
  cwd: BACKEND_DIR,
  url: API_READY_URL,
  env: djangoEnvForServer(),
  reuseExistingServer: !process.env.CI,
  timeout: 180_000,
  stdout: "pipe" as const,
  stderr: "pipe" as const,
};

const webServer = liveProjectSelected() ? [djangoServer, nextServer] : [nextServer];

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.{ts,tsx}",
  globalSetup: "./tests/live/global-setup.ts",
  fullyParallel: true,
  // One worker whenever Django is part of the run, so the live files execute in
  // discovery order (alphabetical: b5-sale, dashboard, payroll, reports,
  // settings) and each spec sees what the previous one left behind. The stubbed
  // invocation does not select the live project and keeps the parallel default -
  // it intercepts its own requests and shares no state worth serializing.
  workers: liveProjectSelected() ? 1 : undefined,
  reporter: "list",
  use: {
    baseURL: FRONTEND_ORIGIN,
    trace: "on-first-retry",
  },
  webServer,
  projects: [
    {
      name: "chromium",
      testIgnore: "**/live/**",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "live",
      // Scoped to `*.spec.ts` on purpose: `**/live/**` would also collect
      // environment.ts and global-setup.ts as tests, and Playwright refuses to let
      // one test file import another.
      testMatch: "**/live/**/*.spec.ts",
      // The live specs share one database, so they take it in turn rather than
      // all at once. Within the project, `mode: "serial"` in the spec keeps one
      // story in order; `workers: 1` below is what keeps the files in order -
      // `fullyParallel: false` only stops tests *within* a file from spreading
      // across workers, while separate files are still distributed in parallel.
      // The stories depend on each other's leftovers (reports reads the run
      // payroll approved, and counts the sale b5 voided), so that parallelism
      // was a race the docstrings already assumed could not happen.
      fullyParallel: false,
      use: { ...devices["Desktop Chrome"] },
      // Fifteen seconds for assertions, where the default is five.
      //
      // Every assertion here waits on two servers and a database: the browser
      // talks to Next, Next proxies to Django, Django queries Postgres. A cold
      // `next start` also pays for rendering a route the first time it is
      // requested. Five seconds is occasionally not enough for the first
      // assertion after a cold boot, and it failed that way before
      // `FRONTEND_READY_URL` warmed the sign-in page.
      //
      // This does not make the suite laxer. A wrong answer still fails; it just
      // fails after fifteen seconds instead of five. What it stops is a timing
      // failure being reported as a behavioural one, which is the more expensive
      // mistake of the two.
      expect: { timeout: 15_000 },
    },
  ],
});
