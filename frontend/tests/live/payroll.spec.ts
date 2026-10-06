/**
 * Roadmap C5's month-with-a-status is only worth shipping if a browser, talking
 * to this Django, can walk a month through its whole lifecycle and have the
 * backend agree at each step.
 *
 * The stubbed spec at `tests/e2e/payroll.spec.ts` proves the screen calls the
 * routes it calls. That suite concedes line by line what a real payment
 * actually looks like, because a stub is the author's guess about what Django
 * would have said. Nothing here intercepts a request: the seed created Seble's
 * row, Django pays it, and the approvals below are real writes through the
 * roles' real permissions.
 *
 * The story runs in two sign-ins, because the two acts are owned by different
 * people (spec A14.1):
 *
 * 1. The Manager generates the current month and is refused "Approve" - the
 *    owner-only button simply is not shown - while the payslip on screen is
 *    the seeded wage, not a number typed by a test.
 * 2. The Owner approves the run and then marks it paid. Each step is read back
 *    over HTTP with the browser's own cookie, because a screen agreeing with
 *    itself is not evidence that status moved.
 *
 * The run period is the current month because the screen defaults to it and
 * the seed resets between runs, so "the generated run" is always unique.
 */

import { expect, test, type Page } from "@playwright/test";

import { readSeedSummary, type SeededUser } from "./environment";

const seed = readSeedSummary();

/** Sign in through the real form and wait for the guard to admit us. */
async function signIn(page: Page, user: SeededUser): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Username").fill(user.username);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

/**
 * The status chip in the run's summary box. A bare `getByText("Paid")` would
 * also match the KPI label of that name, so the chip is located as the span
 * whose text is exactly the status.
 */
function chip(page: Page, status: string) {
  return page.locator("span").filter({ hasText: new RegExp(`^${status}$`) });
}

/** The generated run for this calendar month, read back over HTTP. */
async function readRun(page: Page): Promise<Record<string, unknown> | null> {
  const response = await page.request.get("/api/v1/payroll/runs/?page_size=100");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Record<string, unknown>[] };
  const now = new Date();
  const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return body.results.find((run) => String(run.period_month).startsWith(month)) ?? null;
}

/** The one payslip line of a run, read back over HTTP. */
async function readItem(page: Page, runId: number): Promise<Record<string, unknown> | null> {
  const response = await page.request.get(`/api/v1/payroll/runs/${runId}/items/?page_size=100`);
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Record<string, unknown>[] };
  return body.results[0] ?? null;
}

test.describe.configure({ mode: "serial" });

test("a Manager generates the month and cannot approve it", async ({ page }) => {
  await signIn(page, seed.manager);
  await page.goto("/payroll/runs");

  // Nothing for this month yet - only the generation form.
  await expect(page.getByText(/Generate payroll for/)).toBeVisible();
  await expect(chip(page, "Generated")).toHaveCount(0);

  await page.getByRole("button", { name: "Generate run" }).click();

  // The run appears with a single payslip at the seeded wage.
  await expect(chip(page, "Generated")).toBeVisible();
  const employeeRow = page.getByRole("row").filter({ hasText: seed.payroll.full_name });
  await expect(employeeRow).toHaveCount(1);
  await expect(employeeRow).toContainText("12,000.00 ETB");

  // The money the screen shows is the seeded wage, served by Django rather
  // than assembled by the test - the seed wrote "12000.00", the serializers
  // round-trip fixed-point money, and the two match.
  const run = await readRun(page);
  expect(run).not.toBeNull();
  expect(run).toMatchObject({
    status: "GENERATED",
    gross_total: seed.payroll.monthly_wage,
    net_total: seed.payroll.monthly_wage,
  });
  const item = await readItem(page, Number((run as { id: number }).id));
  expect(item).not.toBeNull();
  expect(item).toMatchObject({
    full_name: seed.payroll.full_name,
    gross_amount: seed.payroll.monthly_wage,
    net_amount: seed.payroll.monthly_wage,
    total_deductions: "0.00",
  });

  // The Manager's permissions stop at generation: the button is not rendered
  // at all, and the screen says who has to sign it.
  await expect(page.getByRole("button", { name: "Approve run" })).toHaveCount(0);
  await expect(page.getByText("An owner approves this run before anything is paid.")).toBeVisible();
});

test("the Owner signs off a month Django really generated", async ({ page }) => {
  await signIn(page, seed.owner);
  await page.goto("/payroll/runs");

  // The Manager's work from the previous step is still standing; the screen
  // defaults to the current month, which is the generated one.
  await expect(chip(page, "Generated")).toBeVisible();

  await page.getByRole("button", { name: "Approve run" }).click();

  await expect(chip(page, "Approved")).toBeVisible();
  await expect(chip(page, "Generated")).toHaveCount(0);
  await expect(page.getByText(/Approved by e2e-owner/)).toBeVisible();

  const approved = await readRun(page);
  expect(approved).not.toBeNull();
  expect(approved).toMatchObject({ status: "APPROVED" });

  // The approved month is now the screen's business to hand over the money.
  await page.getByRole("button", { name: "Mark as paid" }).click();

  await expect(chip(page, "Paid")).toBeVisible();
  await expect(page.getByText("Nothing left to do for this month.")).toBeVisible();

  const paid = await readRun(page);
  expect(paid).not.toBeNull();
  expect(paid).toMatchObject({ status: "PAID" });
});
