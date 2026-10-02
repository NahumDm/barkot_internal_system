/**
 * Copy the build output that a standalone server does not include itself.
 *
 * `next build` with `output: "standalone"` emits a self-contained server in
 * `.next/standalone/`, but it deliberately leaves out the client bundle: the
 * assets are large and the deployment decides where they go. `Dockerfile.frontend`
 * does that copy for the production image; `npm start` did not, so running it
 * locally served pages with no JavaScript at all.
 *
 * That is not a cosmetic difference. Every client-side behaviour is inert
 * without the bundle — the session guard added in B2 never runs, no fetch is
 * issued, and nothing hydrates. It was invisible for as long as the E2E tests
 * only asserted server-rendered HTML, and it made the suite look like it was
 * covering the browser when it was covering a static file.
 *
 * Node rather than shell so the same command works on Windows and in CI. A
 * missing `public/` is normal and skipped rather than treated as an error.
 */

import { access, cp } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();

const assets = [
  { from: ".next/static", to: ".next/standalone/.next/static" },
  { from: "public", to: ".next/standalone/public" },
];

for (const { from, to } of assets) {
  const source = path.join(root, from);
  try {
    await access(source);
  } catch {
    console.log(`[standalone] skipping ${from} — not present`);
    continue;
  }

  const destination = path.join(root, to);
  await cp(source, destination, { recursive: true });
  console.log(`[standalone] copied ${from} -> ${to}`);
}
