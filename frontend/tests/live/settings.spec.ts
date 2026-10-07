/**
 * Roadmap C5's Owner-administered accounts, roles and settings, read in a
 * browser against the real backend.
 *
 * The stubbed spec at `tests/e2e/settings.spec.ts` proves the screen calls the
 * routes it calls and a Manager is refused. Nothing here intercepts a request:
 * the user is created with a real POST, read back after it is deactivated with
 * a real GET, and the settings row is patched and read back — the roles
 * catalogue is asserted from its own response, so a Manager's missing grants
 * are the server's answer, not the UI's claim.
 *
 * Two stories, two owners of the screen:
 *
 * 1. The Owner creates a Barman account with a temporary password, deactivates
 *    it (the audit trail's alternative to deleting), and raises the password
 *    max age — each step confirmed over HTTP before the screen is left.
 * 2. That same screen refused to the Manager is never even asked for the three
 *    admin collections, counted at the network layer.
 *
 * Both stories sign in again after reports, so the first attempt is often
 * throttled by A5; the shared `signIn` waits the window out instead of this
 * suite being reordered or re-seeded. The live suite is serial and shares one
 * Postgres, so roles created here are the residue the next run's fresh seed
 * erases.
 */

import { expect, test, type Page } from "@playwright/test";

import { readSeedSummary } from "./environment";
import { signIn } from "./signin";

const seed = readSeedSummary();

/** A unique-but-memorable login for the account this run creates and then retires. */
const BARMAN_USERNAME = `e2e-barman-${Date.now()}`;

test.describe.configure({ mode: "serial" });

test("the Owner creates, deactivates and reads back a staff account, and patches settings", async ({
  page,
}) => {
  // Two admin writes plus the sign-in's minuted retry window behind them.
  test.setTimeout(240_000);

  await signIn(page, seed.owner);
  await page.goto("/settings");

  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Staff accounts" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Roles" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "System" })).toBeVisible();

  // --- Roles: the catalogue the backend serves. The Owner holds the admin
  // grant the Manager must not, read as data rather than from the screen.
  const roles = await readAs<{ results: { code: string; permissions: string[] }[] }>(
    page,
    "/api/v1/roles/?page_size=100",
  );
  const ownerRole = roles.results.find((role) => role.code === "OWNER");
  const managerRole = roles.results.find((role) => role.code === "MANAGER");
  expect(ownerRole?.permissions).toContain("accounts.manage_users");
  expect(managerRole?.permissions).not.toContain("accounts.manage_users");

  // --- Create a Barman with a temporary password: a real write that returns
  // the account the screen then lists.
  const form = page.locator("form");
  await expect(form.getByLabel("Role")).not.toBeDisabled();
  await form.getByLabel("Login name").fill(BARMAN_USERNAME);
  await form.getByLabel("Role").selectOption("BARMAN");
  await form.getByLabel("Temporary password", { exact: true }).fill(seed.owner.password);
  await form.getByRole("button", { name: "Create staff account" }).click();

  const row = page.getByRole("row", { name: new RegExp(BARMAN_USERNAME) });
  await expect(row).toBeVisible();
  await expect(row.getByText("Temporary password — reset on sign-in")).toBeVisible();

  // --- Deactivate it. There is no delete anywhere in accounts, so "retire" is
  // a status flip, and the HTTP read-back shows both flags dropping together.
  await row.getByRole("button", { name: "Edit" }).click();
  await row.getByRole("checkbox").uncheck();
  await row.getByRole("button", { name: "Save" }).click();
  await expect(row.getByText("Inactive", { exact: true })).toBeVisible();

  const users = await readAs<{
    results: { username: string; role: string; is_active: boolean; is_staff: boolean }[];
  }>(page, "/api/v1/users/?page_size=200");
  const created = users.results.find((user) => user.username === BARMAN_USERNAME);
  expect(created).toMatchObject({
    role: "BARMAN",
    is_active: false,
    is_staff: false,
  });

  // --- Patch the system settings and read the row back: the screen's value
  // travelled, and the server recorded who changed it.
  await page.getByLabel("Password max age (days)").fill("90");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText("Saved.", { exact: true })).toBeVisible();

  const settings = await readAs<{
    password_max_age_days: number;
    session_timeout_minutes: number;
    updated_by: string | null;
  }>(page, "/api/v1/settings/");
  expect(settings.password_max_age_days).toBe(90);
  expect(settings.session_timeout_minutes).toBeGreaterThan(0);
  expect(settings.updated_by).toBe(seed.owner.username);
});

test("a Manager is refused the account settings without a single admin request", async ({
  page,
}) => {
  test.setTimeout(240_000);

  let adminRequests = 0;
  page.on("request", (request) => {
    const url = request.url();
    if (
      url.includes("/api/v1/users/") ||
      url.includes("/api/v1/roles/") ||
      url.includes("/api/v1/settings/")
    ) {
      adminRequests += 1;
    }
  });

  await signIn(page, seed.manager);
  await page.goto("/settings");

  await expect(
    page.getByText("Your role does not include account settings. Ask an owner if you need access."),
  ).toBeVisible();
  expect(adminRequests).toBe(0);
});

/** GET a response over the browser's own session and assert it succeeded. */
async function readAs<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(path);
  expect(response.status()).toBe(200);
  return (await response.json()) as T;
}
