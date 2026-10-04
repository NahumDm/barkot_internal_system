/**
 * Put a known database behind the live specs, once per run.
 *
 * Playwright's `webServer` starts Django; this makes that Django worth talking
 * to. It migrates, wipes whatever the previous run left behind, and seeds the
 * fixtures - writing them to a file the specs read, so the credentials and ids
 * live in exactly one place (`backend/.../seed_e2e.py`) instead of being copied
 * into TypeScript and left to drift.
 *
 * Two details are deliberate.
 *
 * **Migrate runs here as well as in the web server command.** `migrate` is
 * idempotent, and running it in both places means this file does not care
 * whether Playwright starts the web servers before or after global setup. Making
 * correctness depend on that ordering, which is an implementation detail, would
 * be a poor trade for saving one fast no-op.
 *
 * **Seeding is skipped when the live project is not selected.** `npm run
 * test:e2e:stubbed` exists for working on the frontend with no Postgres running,
 * and it should not fail because a database it never talks to is absent. The
 * config reads the same flag and leaves Django out of `webServer` to match, so
 * the two agree on whether a backend is part of the run.
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import {
  BACKEND_DIR,
  djangoEnv,
  E2E_API_PORT,
  liveProjectSelected,
  pythonExecutable,
  readSeedSummary,
  SEED_FILE,
  type SeedSummary,
} from "./environment";

/** Run `manage.py` and return what it printed. */
function manage(args: string[]): string {
  return execFileSync(pythonExecutable(), ["manage.py", ...args], {
    cwd: BACKEND_DIR,
    env: djangoEnv(),
    encoding: "utf8",
    // Piped, not inherited: `seed_e2e --json` prints a single line of JSON and
    // anything else on stdout would corrupt it. Errors still surface, because a
    // non-zero exit throws with stderr attached.
    stdio: ["ignore", "pipe", "pipe"],
  });
}

export default function globalSetup(): void {
  if (!liveProjectSelected()) return;

  manage(["migrate", "--no-input"]);

  const printed = manage(["seed_e2e", "--reset", "--json"]);
  const summary = JSON.parse(printed.trim().split(/\r?\n/).at(-1) ?? "") as SeedSummary;

  fs.mkdirSync(path.dirname(SEED_FILE), { recursive: true });
  fs.writeFileSync(SEED_FILE, `${JSON.stringify(summary, null, 2)}\n`);

  // Fail here rather than inside a test: a missing or unusable database is a
  // setup problem, and reporting it as a dozen failed specs would bury it.
  const verified = readSeedSummary();
  if (verified.product.opening_stock === "0") {
    throw new Error("seed_e2e produced a product with no stock to sell.");
  }

  console.log(
    `Seeded ${verified.database} for the live E2E specs: ${verified.product.sku} at ` +
      `${verified.product.unit_price}, ${verified.product.opening_stock} on the shelf ` +
      `(Django on :${E2E_API_PORT}).`,
  );
}
